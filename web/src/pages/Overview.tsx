import { useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, fmtMs, fmtNum, fmtTime, fmtUsd, Stats } from "../api";
import { ScopeBar, useScope } from "../scope";
import { Card, Stat, Table, Empty } from "../ui";
import LiveTail from "../LiveTail";

export default function Overview() {
  const scope = useScope();
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () =>
      api
        .get<Stats>(`/admin/stats?${scope.scopeQuery()}`)
        .then(setStats)
        .catch((e) => setError(String(e.message)));
    load();
    const timer = setInterval(load, 10_000);
    return () => clearInterval(timer);
  }, [scope.keyId, scope.provider, scope.model, scope.instanceId, scope.range, scope.granularity]);

  if (error) return <Empty>{error}</Empty>;
  if (!stats) return <Empty>Loading…</Empty>;

  const s = stats.summary;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Overview</h1>
        <ScopeBar />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Requests" value={fmtNum(s.requests)} />
        <Stat label="Tokens in" value={fmtNum(s.tokens_in)} />
        <Stat label="Tokens out" value={fmtNum(s.tokens_out)} />
        <Stat
          label="Est. cost"
          value={fmtUsd(s.cost_usd)}
          sub={`${fmtNum(s.tokens_cached)} cached`}
        />
        <Stat label="Error rate" value={(s.error_rate * 100).toFixed(1) + "%"} />
        <Stat
          label="Overhead p50/p95"
          value={`${fmtMs(s.overhead_p50_ms)} / ${fmtMs(s.overhead_p95_ms)}`}
          sub="gateway hop, subtract for benchmarks"
        />
      </div>

      <Card title="Requests & cost">
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={stats.series}>
            <defs>
              <linearGradient id="req" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#232329" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="bucket" stroke="#71717a" fontSize={11} tickLine={false} />
            <YAxis stroke="#71717a" fontSize={11} tickLine={false} axisLine={false} />
            <ChartTooltip
              contentStyle={{
                background: "#101013",
                border: "1px solid #232329",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Area
              type="monotone"
              dataKey="requests"
              stroke="#6366f1"
              fill="url(#req)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Tokens (stacked in / out / cached)">
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={stats.series}>
              <CartesianGrid stroke="#232329" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="bucket" stroke="#71717a" fontSize={11} tickLine={false} />
              <YAxis stroke="#71717a" fontSize={11} tickLine={false} axisLine={false} />
              <ChartTooltip
                contentStyle={{
                  background: "#101013",
                  border: "1px solid #232329",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line type="monotone" dataKey="tokens_in" stroke="#818cf8" dot={false} strokeWidth={1.5} />
              <Line type="monotone" dataKey="tokens_out" stroke="#34d399" dot={false} strokeWidth={1.5} />
              <Line type="monotone" dataKey="tokens_cached" stroke="#fbbf24" dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
        <LiveTail maxEvents={50} listClassName="max-h-72" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {(
          [
            ["Top keys", stats.top_keys],
            ["Top models", stats.top_models],
            ["Top providers", stats.top_providers],
          ] as const
        ).map(([title, rows]) => (
          <Card key={title} title={title}>
            {rows.length === 0 ? (
              <Empty>No data in range</Empty>
            ) : (
              <Table head={["Name", "Requests", "Cost"]}>
                {rows.map((r) => (
                  <tr key={r.name}>
                    <td className="px-3 py-1.5 font-mono text-[11.5px]">{r.name}</td>
                    <td className="px-3 py-1.5 tabular-nums">{fmtNum(r.requests)}</td>
                    <td className="px-3 py-1.5 tabular-nums">{fmtUsd(r.cost_usd)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
