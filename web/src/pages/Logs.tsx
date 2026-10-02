import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { api, fmtMs, fmtNum, fmtTime, fmtUsd, LogRow } from "../api";
import { Badge, Button, Card, Empty, Input, Modal, Select, Table } from "../ui";

function PreviewBlock({ label, body }: { label: string; body: string }) {
  return (
    <div className="mt-3">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </div>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-[var(--color-line)] bg-zinc-900/60 p-2.5 font-mono text-[10.5px] text-zinc-300">
        {body}
      </pre>
    </div>
  );
}

function LogDetail({ row, onClose }: { row: LogRow; onClose: () => void }) {
  const overhead =
    row.latency_total_ms != null && row.upstream_ms != null && row.latency_total_ms >= row.upstream_ms
      ? row.latency_total_ms - row.upstream_ms
      : null;
  return (
    <Modal title={`Request ${row.id}`} onClose={onClose} wide>
      <div className="grid grid-cols-2 gap-3 text-[12px] md:grid-cols-4">
        {[
          ["Time", fmtTime(row.ts)],
          ["Endpoint", row.endpoint],
          ["Provider", row.provider ?? "–"],
          ["Model", row.model ?? "–"],
          ["Status", String(row.status_code ?? "–")],
          ["Stream", row.is_stream ? "yes" : "no"],
          ["Client", row.client_ip ?? "–"],
          ["Machine", row.instance_id.slice(0, 8)],
          ["Latency total", fmtMs(row.latency_total_ms)],
          ["Upstream", fmtMs(row.upstream_ms)],
          ["Tollgate overhead", overhead != null ? fmtMs(overhead) : "–"],
          ["Alias used", row.alias_used ?? "–"],
        ].map(([label, value]) => (
          <div key={label} className="rounded-md border border-[var(--color-line)] px-2.5 py-1.5">
            <div className="text-[10px] uppercase text-[var(--color-muted)]">{label}</div>
            <div className="mt-0.5 font-medium">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-md border border-[var(--color-line)] p-3">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted)]">
          Tokens & cost math {row.estimated && <Badge tone="warn">estimated</Badge>}
        </div>
        <div className="space-y-1 font-mono text-[11.5px] text-zinc-300">
          <div>tokens_in:    {fmtNum(row.tokens_in)}</div>
          <div>tokens_out:   {fmtNum(row.tokens_out)}</div>
          <div>cache_read:   {fmtNum(row.cache_read)}  (billed at cache-read rate)</div>
          <div>cache_write:  {fmtNum(row.cache_write)} (billed at cache-write rate)</div>
          <div className="pt-1 text-emerald-400">
            cost_usd: {row.cost_usd.toFixed(8)} (frozen at log time, band #{row.price_band_id ?? "n/a"})
          </div>
        </div>
      </div>

      {row.fallback_hops && row.fallback_hops.length > 0 && (
        <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-[11.5px]">
          <div className="mb-1 font-medium text-amber-400">Fallback hops</div>
          {row.fallback_hops.map((h, i) => (
            <div key={i}>
              {i + 1}. {h.provider} — {h.status ? `HTTP ${h.status}` : h.error}
            </div>
          ))}
        </div>
      )}

      {row.error && (
        <div className="mt-3 rounded-md border border-red-500/30 bg-red-500/5 p-3 font-mono text-[11.5px] text-red-400">
          {row.error}
        </div>
      )}
      <div className="mt-3 text-[11px] text-[var(--color-muted)]">
        req {fmtNum(row.request_bytes)} B · resp {fmtNum(row.response_bytes)} B
      </div>

      {row.request_preview != null && (
        <PreviewBlock label="Request preview (redacted)" body={row.request_preview} />
      )}
      {row.response_preview != null && (
        <PreviewBlock label="Response preview (redacted)" body={row.response_preview} />
      )}
    </Modal>
  );
}

export default function Logs() {
  const [data, setData] = useState<{ total: number; items: LogRow[] } | null>(null);
  const [filters, setFilters] = useState({ key_id: "", provider: "", model: "", status: "" });
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<LogRow | null>(null);
  const page = 50;

  useEffect(() => {
    setOffset(0);
  }, [filters]);

  useEffect(() => {
    const p = new URLSearchParams();
    if (filters.key_id) p.set("key_id", filters.key_id);
    if (filters.provider) p.set("provider", filters.provider);
    if (filters.model) p.set("model", filters.model);
    if (filters.status) p.set("status", filters.status);
    p.set("limit", String(page));
    p.set("offset", String(offset));
    api
      .get<{ total: number; items: LogRow[] }>(`/admin/logs?${p.toString()}`)
      .then(setData);
  }, [filters, offset]);

  const exportUrl = (format: string) => {
    const p = new URLSearchParams();
    if (filters.key_id) p.set("key_id", filters.key_id);
    if (filters.provider) p.set("provider", filters.provider);
    if (filters.model) p.set("model", filters.model);
    if (filters.status) p.set("status", filters.status);
    return `/admin/logs/export?format=${format}&${p.toString()}`;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Logs</h1>
        <div className="flex gap-2">
          <Button onClick={() => api.download(exportUrl("csv"))}>
            <Download size={12} /> CSV
          </Button>
          <Button onClick={() => api.download(exportUrl("json"))}>
            <Download size={12} /> JSON
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="key id"
          value={filters.key_id}
          onChange={(e) => setFilters({ ...filters, key_id: e.target.value })}
          className="w-44"
        />
        <Input
          placeholder="provider"
          value={filters.provider}
          onChange={(e) => setFilters({ ...filters, provider: e.target.value })}
          className="w-32"
        />
        <Input
          placeholder="model"
          value={filters.model}
          onChange={(e) => setFilters({ ...filters, model: e.target.value })}
          className="w-32"
        />
        <Select
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
        >
          <option value="">any status</option>
          <option value="200">200</option>
          <option value="400">400</option>
          <option value="401">401</option>
          <option value="429">429</option>
          <option value="500">500</option>
          <option value="502">502</option>
        </Select>
      </div>

      <Card title={data ? `${fmtNum(data.total)} requests` : "…"}>
        {!data || data.items.length === 0 ? (
          <Empty>No matching requests.</Empty>
        ) : (
          <Table
            head={["Time", "Key", "Provider", "Model", "Status", "Tokens", "Cost", "Latency"]}
          >
            {data.items.map((row) => (
              <tr
                key={row.id}
                className="cursor-pointer hover:bg-zinc-900/40"
                onClick={() => setDetail(row)}
              >
                <td className="px-3 py-1.5 whitespace-nowrap text-[11px] text-[var(--color-muted)]">
                  {fmtTime(row.ts)}
                </td>
                <td className="px-3 py-1.5 font-mono text-[11px]">
                  {row.key ?? "–"}
                  {row.project && (
                    <span className="ml-1 text-[10px] text-[var(--color-muted)]">{row.project}</span>
                  )}
                </td>
                <td className="px-3 py-1.5">{row.provider ?? "–"}</td>
                <td className="px-3 py-1.5">
                  {row.model ?? "–"}
                  {row.alias_used && (
                    <span className="ml-1 text-[10px] text-indigo-400">via {row.alias_used}</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  <Badge tone={row.status_code && row.status_code < 400 ? "ok" : "error"}>
                    {row.status_code ?? "–"}
                  </Badge>
                </td>
                <td className="px-3 py-1.5 tabular-nums text-[11px]">
                  {fmtNum(row.tokens_in)}→{fmtNum(row.tokens_out)}
                  {row.cache_read + row.cache_write > 0 && (
                    <span className="ml-1 text-amber-500">
                      (+{fmtNum(row.cache_read + row.cache_write)}c)
                    </span>
                  )}
                  {row.estimated && <span className="ml-1 text-[10px] text-[var(--color-muted)]">est</span>}
                </td>
                <td className="px-3 py-1.5 tabular-nums">{fmtUsd(row.cost_usd)}</td>
                <td className="px-3 py-1.5 tabular-nums text-[11px] text-[var(--color-muted)]">
                  {fmtMs(row.latency_total_ms)}
                </td>
              </tr>
            ))}
          </Table>
        )}
        {data && data.total > page && (
          <div className="mt-3 flex items-center justify-between">
            <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - page))}>
              ← Newer
            </Button>
            <span className="text-[11px] text-[var(--color-muted)]">
              {offset + 1}–{Math.min(offset + page, data.total)} of {fmtNum(data.total)}
            </span>
            <Button
              disabled={offset + page >= data.total}
              onClick={() => setOffset(offset + page)}
            >
              Older →
            </Button>
          </div>
        )}
      </Card>

      {detail && <LogDetail row={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
