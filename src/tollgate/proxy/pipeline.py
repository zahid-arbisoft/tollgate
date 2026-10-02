"""The request pipeline (plan §9): auth → route → upstream → stream/tee → finalize."""

from __future__ import annotations

import json
import time

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..metering.finalize import finalize_request
from ..security.redaction import make_preview
from .providers.base import ProxyRequestContext, RouteContext, SSECollector
from .providers.openai import safe_json_loads
from .providers.registry import error_payload_for_path, get_adapter
from .router import RouteError, resolve_routes

HOP_FAILURE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def tollgate_error(request: Request, status: int, reason: str, message: str) -> JSONResponse:
    payload = error_payload_for_path(request.url.path, status, message, reason)
    return JSONResponse(payload, status_code=status, headers={"x-tollgate-error": reason})


async def proxy_request(request: Request, endpoint_path: str, key) -> Response:
    """key is the authenticated VirtualKey (auth dependency already ran)."""
    settings = request.app.state.settings
    http: httpx.AsyncClient = request.app.state.http
    t0 = time.perf_counter_ns()

    raw_body = await request.body()
    log_bodies = await _bodies_enabled(request.app)
    req_preview = make_preview(raw_body) if log_bodies else None
    parsed = safe_json_loads(raw_body)
    if parsed is None and endpoint_path != "/v1/models":
        return tollgate_error(request, 400, "invalid_json", "Request body must be JSON.")

    requested_model = None
    if parsed is not None:
        m = parsed.get("model")
        requested_model = m if isinstance(m, str) else None
    is_stream = bool(parsed.get("stream")) if parsed else False

    async with request.app.state.session_factory() as session:
        try:
            hops, alias_used = await resolve_routes(session, endpoint_path, requested_model, key)
        except RouteError as exc:
            return tollgate_error(request, exc.status_code, exc.reason, exc.message)

    ctx = ProxyRequestContext(
        key_id=key.id if key else None,
        client_ip=request.client.host if request.client else None,
        t0_ns=t0,
    )

    # Limits pre-check (Batch 4): raises LimitExceeded → native 429.
    from ..limits.enforcer import LimitExceeded, precheck

    try:
        await precheck(request.app, key, endpoint_path)
    except LimitExceeded as exc:
        return _limit_response(request, exc)

    last_error: tuple[int, bytes, str] | None = None
    for hop in hops:
        adapter = get_adapter(hop.provider.type)
        api_key = (
            request.app.state.secrets.get(f"provider:{hop.provider.id}")
            if hop.provider.secret_handle
            else None
        )

        body_dict = dict(parsed) if parsed else {}
        body_dict = adapter.prepare_body(body_dict)
        if hop.upstream_model and hop.upstream_model != requested_model:
            body_dict["model"] = hop.upstream_model
        out_body = json.dumps(body_dict).encode() if parsed else b""

        url = adapter.upstream_url(hop.provider.base_url, endpoint_path)
        headers = {"content-type": "application/json", **adapter.auth_headers(api_key)}

        route_ctx = RouteContext(
            provider_type=hop.provider.type,
            base_url=hop.provider.base_url,
            api_key=api_key,
            endpoint_path=endpoint_path,
            request_body=out_body,
            is_stream=is_stream,
        )

        t_up = time.perf_counter_ns()
        req = httpx.Request("POST", url, headers=headers, content=out_body)
        # Per-provider timeout rides on extensions (httpx.send has no timeout kwarg).
        t = httpx.Timeout(hop.provider.timeout_s, connect=min(30.0, hop.provider.timeout_s))
        req.extensions["timeout"] = {
            "connect": t.connect,
            "read": t.read,
            "write": t.write,
            "pool": t.pool,
        }
        upstream_resp = None
        # Connect-only retries: safe (no bytes sent upstream, can't double-charge).
        # Read/write timeouts are NOT retried — fail closed per plan §9.
        for attempt in range(max(1, hop.provider.retries + 1)):
            try:
                upstream_resp = await http.send(req, stream=True)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt >= hop.provider.retries:
                    break
        if upstream_resp is None:
            ctx.hops.append({"provider": hop.provider.name, "error": "connect_failed"})
            err = json.dumps(
                {"error": {"message": f"upstream unreachable: {hop.provider.name}"}}
            ).encode()
            last_error = (502, err, "application/json")
            continue

        ctx.upstream_t0_ns = t_up
        ctx.upstream_first_byte_ns = time.perf_counter_ns()

        if upstream_resp.status_code in HOP_FAILURE_STATUSES and hop is not hops[-1]:
            err_bytes = await upstream_resp.aread()
            await upstream_resp.aclose()
            ctx.hops.append({"provider": hop.provider.name, "status": upstream_resp.status_code})
            last_error = (
                upstream_resp.status_code,
                err_bytes,
                upstream_resp.headers.get("content-type", "application/json"),
            )
            continue  # try the next hop in the fallback chain

        return await _respond(
            request,
            key,
            hop,
            adapter,
            route_ctx,
            ctx,
            upstream_resp,
            requested_model,
            alias_used,
            raw_body,
            is_stream,
            settings,
            req_preview,
            log_bodies,
        )

    status, body, ctype = last_error or (502, b'{"error":"no upstream"}', "application/json")
    await _log_failure(
        request, key, endpoint_path, ctx, requested_model, status, raw_body, req_preview=req_preview
    )
    return Response(
        content=body,
        status_code=status,
        media_type=ctype,
        headers={"x-tollgate-error": "upstream_failed"},
    )


def _limit_response(request: Request, exc) -> JSONResponse:
    payload = error_payload_for_path(request.url.path, exc.status_code, exc.message, exc.reason)
    headers = {"x-tollgate-error": exc.reason}
    if exc.reset_at is not None:
        headers["x-tollgate-limit-reset"] = exc.reset_at.isoformat()
    return JSONResponse(payload, status_code=exc.status_code, headers=headers)


async def _limit_cut_now(app, key) -> bool:
    """True when the key is already over a reject limit (mid-stream check)."""
    from ..limits.enforcer import LimitExceeded, precheck

    try:
        await precheck(app, key, "")
    except LimitExceeded:
        return True
    return False


def _cut_event(adapter) -> bytes:
    """A clean, native-shaped SSE termination event when a stream is cut."""
    import json as _json

    payload = adapter.error_payload(
        429, "Limit exceeded - stream terminated by Tollgate.", "limit_exceeded"
    )
    return b"event: error\ndata: " + _json.dumps(payload).encode() + b"\n\ndata: [DONE]\n\n"


async def _respond(
    request,
    key,
    hop,
    adapter,
    route_ctx,
    ctx,
    upstream_resp,
    requested_model,
    alias_used,
    raw_body,
    is_stream,
    settings,
    req_preview=None,
    log_bodies=False,
) -> Response:
    passthrough_headers = {
        k: v
        for k, v in upstream_resp.headers.items()
        if k.lower() in {"content-type", "request-id", "openai-version", "anthropic-version"}
    }
    meta_headers = {
        "x-tollgate-key": key.prefix if key else "-",
        "x-tollgate-provider": hop.provider.name,
        "x-tollgate-model": hop.upstream_model,
    }
    if alias_used:
        meta_headers["x-tollgate-alias"] = alias_used

    if is_stream and upstream_resp.status_code < 400:
        collector = SSECollector()
        media_type = upstream_resp.headers.get("content-type", "text/event-stream")
        first_chunk_at: list[float] = []

        async def stream_and_meter():
            resp_bytes = 0
            error: str | None = None
            try:
                async for chunk in upstream_resp.aiter_raw():
                    if not first_chunk_at:
                        first_chunk_at.append(time.perf_counter_ns())
                        ctx.upstream_first_byte_ns = first_chunk_at[0]
                    resp_bytes += len(chunk)
                    collector.feed(chunk)
                    # Mid-stream limit cut: providers emit usage events near the
                    # end of a stream; when one shows up, re-check limits before
                    # forwarding further bytes.
                    if b"usage" in chunk and await _limit_cut_now(request.app, key):
                        error = "limit_cut"
                        yield _cut_event(adapter)
                        break
                    yield chunk
            except GeneratorExit:
                error = "client_disconnected"
                raise
            except Exception as exc:  # mid-stream upstream failure — still meter
                error = f"stream_interrupted:{type(exc).__name__}"
            finally:
                await upstream_resp.aclose()
                usage = adapter.extract_usage(None, collector, route_ctx)
                await finalize_request(
                    request.app,
                    ctx=ctx,
                    key=key,
                    endpoint=route_ctx.endpoint_path,
                    provider=hop.provider.name,
                    model=hop.upstream_model,
                    alias_used=alias_used,
                    status_code=upstream_resp.status_code,
                    usage=usage,
                    response_bytes=resp_bytes,
                    request_bytes=len(raw_body),
                    is_stream=True,
                    error=error,
                    request_preview=req_preview,
                )

        return StreamingResponse(
            stream_and_meter(),
            media_type=media_type,
            headers={**passthrough_headers, **meta_headers},
        )

    try:
        body_bytes = await upstream_resp.aread()
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError):
        await upstream_resp.aclose()
        await _log_failure(
            request,
            key,
            route_ctx.endpoint_path,
            ctx,
            requested_model,
            504,
            raw_body,
            error="upstream_read_timeout",
        )
        return tollgate_error(
            request, 504, "upstream_timeout", "Upstream timed out reading the response."
        )
    await upstream_resp.aclose()

    if upstream_resp.status_code >= 400:
        await _log_failure(
            request,
            key,
            route_ctx.endpoint_path,
            ctx,
            requested_model,
            upstream_resp.status_code,
            raw_body,
        )
        return Response(
            content=body_bytes,
            status_code=upstream_resp.status_code,
            media_type=upstream_resp.headers.get("content-type", "application/json"),
            headers=meta_headers,
        )

    parsed_resp = safe_json_loads(body_bytes)
    usage = adapter.extract_usage(parsed_resp, None, route_ctx)
    resp_preview = make_preview(body_bytes) if log_bodies else None
    await finalize_request(
        request.app,
        ctx=ctx,
        key=key,
        endpoint=route_ctx.endpoint_path,
        provider=hop.provider.name,
        model=hop.upstream_model,
        alias_used=alias_used,
        status_code=upstream_resp.status_code,
        usage=usage,
        response_bytes=len(body_bytes),
        request_bytes=len(raw_body),
        is_stream=False,
        request_preview=req_preview,
        response_preview=resp_preview,
    )
    return Response(
        content=body_bytes,
        status_code=upstream_resp.status_code,
        media_type=upstream_resp.headers.get("content-type", "application/json"),
        headers={**passthrough_headers, **meta_headers},
    )


async def _log_failure(
    request,
    key,
    endpoint_path,
    ctx,
    requested_model,
    status,
    raw_body,
    error: str | None = None,
    req_preview: str | None = None,
):
    await finalize_request(
        request.app,
        ctx=ctx,
        key=key,
        endpoint=endpoint_path,
        provider=None,
        model=requested_model,
        alias_used=None,
        status_code=status,
        usage=None,
        response_bytes=0,
        request_bytes=len(raw_body),
        is_stream=False,
        error=error or f"http_{status}",
        request_preview=req_preview,
    )


async def _bodies_enabled(app) -> bool:
    """DB setting overrides the config default (Settings page toggle)."""
    from ..store.models import Setting

    async with app.state.session_factory() as session:
        row = await session.get(Setting, "log_bodies")
        if row is not None and isinstance(row.value, bool):
            return row.value
    return app.state.settings.log_bodies
