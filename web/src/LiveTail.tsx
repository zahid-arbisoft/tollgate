import { useEffect, useRef, useState } from "react";
import { Radio, Trash2 } from "lucide-react";
import { fmtMs, fmtNum, fmtTime, fmtUsd } from "./api";
import { Badge, Card, Empty } from "./ui";

export interface TailEvent {
  type: string;
  ts?: string;
  model?: string;
  provider?: string;
  status?: number;
  cost_usd?: number;
  tokens_in?: number;
  tokens_out?: number;
  latency_ms?: number;
  metric?: string;
  window?: string;
}

/** Live SSE tail. Newest on top; shared by the Overview card and the
 * full-page Live view (maxEvents + listClassName control the sizing). */
export default function LiveTail({
  maxEvents = 50,
  listClassName = "max-h-72",
}: {
  maxEvents?: number;
  listClassName?: string;
}) {
  const [events, setEvents] = useState<TailEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const token = encodeURIComponent(
      localStorage.getItem("tollgate-admin-token") ?? "",
    );
    const es = new EventSource(`/admin/events/stream?token=${token}`);
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev) => {
      try {
        const parsed = JSON.parse(ev.data) as TailEvent;
        setEvents((prev) => [parsed, ...prev].slice(0, maxEvents));
      } catch {
        /* ignore */
      }
    };
    return () => es.close();
  }, [maxEvents]);

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          <Radio size={13} className={connected ? "text-emerald-400" : "text-zinc-500"} />
          Live tail
          <span className="text-[11px] font-normal text-[var(--color-muted)]">
            {events.length} events
          </span>
        </span>
      }
      right={
        <button
          className="inline-flex items-center gap-1 text-[11px] text-[var(--color-muted)] hover:text-zinc-200"
          onClick={() => setEvents([])}
        >
          <Trash2 size={12} /> Clear
        </button>
      }
    >
      {events.length === 0 ? (
        <Empty>Waiting for requests…</Empty>
      ) : (
        <div className={`space-y-1 overflow-y-auto ${listClassName}`}>
          {events.map((ev, i) => (
            <div
              key={i}
              className="flex items-center gap-3 rounded border border-[var(--color-line)] bg-zinc-900/40 px-2.5 py-1.5 text-[11.5px]"
            >
              {ev.type === "request" ? (
                <>
                  <Badge tone={ev.status && ev.status < 400 ? "ok" : "error"}>
                    {ev.status}
                  </Badge>
                  <span className="font-medium">{ev.model ?? "?"}</span>
                  <span className="text-[var(--color-muted)]">{ev.provider}</span>
                  <span className="ml-auto tabular-nums text-[var(--color-muted)]">
                    {ev.ts ? fmtTime(ev.ts) : ""}
                  </span>
                  <span className="tabular-nums text-[var(--color-muted)]">
                    {fmtNum(ev.tokens_in)}→{fmtNum(ev.tokens_out)} tok
                  </span>
                  <span className="tabular-nums">{fmtUsd(ev.cost_usd)}</span>
                  <span className="tabular-nums text-[var(--color-muted)]">
                    {fmtMs(ev.latency_ms)}
                  </span>
                </>
              ) : (
                <>
                  <Badge tone={ev.type === "limit_warn" ? "warn" : "error"}>
                    {ev.type === "limit_warn" ? "warn" : "breach"}
                  </Badge>
                  <span>
                    {ev.metric} / {ev.window}
                  </span>
                  <span className="ml-auto text-[var(--color-muted)]">
                    {ev.ts ? fmtTime(ev.ts) : ""}
                  </span>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
