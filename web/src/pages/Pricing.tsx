import { useEffect, useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { api, PriceBand, PriceDiff } from "../api";
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Table } from "../ui";

export default function Pricing() {
  const [bands, setBands] = useState<PriceBand[]>([]);
  const [search, setSearch] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [diff, setDiff] = useState<PriceDiff[] | null>(null);
  const [diffSource, setDiffSource] = useState("litellm");
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const [applied, setApplied] = useState<string>("");

  const load = async (m?: string) => {
    const q = m ? `?model=${encodeURIComponent(m)}` : "";
    setBands(await api.get<PriceBand[]>(`/admin/prices${q}${q ? "&" : "?"}current_only=true`));
  };
  useEffect(() => {
    load();
  }, []);

  const refreshPreview = async () => {
    setBusy(true);
    setApplied("");
    try {
      setDiff(await api.post<PriceDiff[]>("/admin/prices/refresh/preview", { source: diffSource }));
    } catch (e) {
      setApplied("Preview failed: " + String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const applyAll = async () => {
    const result = await api.post<{ applied: number }>("/admin/prices/refresh/apply", {
      accept: "all",
    });
    setDiff(null);
    setApplied(`Applied ${result.applied} price changes.`);
    load(model ?? undefined);
  };

  const shown = bands.filter((b) => !search || b.model.includes(search));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Pricing</h1>
        <Button variant="primary" onClick={() => setManual(true)}>
          <Plus size={13} /> Manual price
        </Button>
      </div>

      <Card
        title="Refresh from community maps"
        right={
          <>
            <Select value={diffSource} onChange={(e) => setDiffSource(e.target.value)}>
              <option value="litellm">LiteLLM</option>
              <option value="openrouter">OpenRouter</option>
            </Select>
            <Button disabled={busy} onClick={refreshPreview}>
              <RefreshCw size={12} className={busy ? "animate-spin" : ""} /> Fetch diff
            </Button>
          </>
        }
      >
        {applied && <div className="mb-2 text-[12px] text-emerald-400">{applied}</div>}
        {!diff ? (
          <Empty>
            Fetch the latest community price map and review the diff before applying — old logs
            keep their old costs either way (prices are effective-dated bands).
          </Empty>
        ) : diff.length === 0 ? (
          <Empty>No changes vs. current bands. You're up to date.</Empty>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[12px] text-[var(--color-muted)]">
                {diff.length} models changed — review, then apply.
              </div>
              <Button variant="primary" onClick={applyAll}>
                Apply all
              </Button>
            </div>
            <div className="max-h-72 overflow-y-auto">
              <Table head={["Model", "Kind", "In $/1M", "Out $/1M", "Cache-read $/1M"]}>
                {diff.map((d) => (
                  <tr key={d.model}>
                    <td className="px-3 py-1.5 font-mono text-[11px]">{d.model}</td>
                    <td className="px-3 py-1.5">
                      <Badge tone={d.kind === "new" ? "info" : "warn"}>{d.kind}</Badge>
                    </td>
                    <td className="px-3 py-1.5 tabular-nums">
                      {d.old_in_per_1m} → <span className="text-amber-400">{d.new_in_per_1m}</span>
                    </td>
                    <td className="px-3 py-1.5 tabular-nums">
                      {d.old_out_per_1m} → <span className="text-amber-400">{d.new_out_per_1m}</span>
                    </td>
                    <td className="px-3 py-1.5 tabular-nums">
                      {d.old_cache_read_per_1m} →{" "}
                      <span className="text-amber-400">{d.new_cache_read_per_1m}</span>
                    </td>
                  </tr>
                ))}
              </Table>
            </div>
          </>
        )}
      </Card>

      <Card
        title={`Current prices (${shown.length}${model ? ` · history: ${model}` : ""})`}
        right={
          <>
            {model && (
              <Button size="xs" onClick={() => { setModel(null); load(); }}>
                back to all
              </Button>
            )}
            <Input
              placeholder="filter model…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-44"
            />
          </>
        }
      >
        {shown.length === 0 ? (
          <Empty>No bands{model ? " for this model" : " (fetch a map or add manual prices)"}.</Empty>
        ) : (
          <div className="max-h-[28rem] overflow-y-auto">
            <Table head={["Model", "In /1M", "Out /1M", "Cache read /1M", "Cache write /1M", "Ctx", "Source", "From"]}>
              {shown.map((b) => (
                <tr
                  key={b.id}
                  className="cursor-pointer hover:bg-zinc-900/40"
                  onClick={() => { setModel(b.model); load(b.model); }}
                  title="click for full band history"
                >
                  <td className="px-3 py-1.5 font-mono text-[11px]">{b.model}</td>
                  <td className="px-3 py-1.5 tabular-nums">{b.price_in_per_1m}</td>
                  <td className="px-3 py-1.5 tabular-nums">{b.price_out_per_1m}</td>
                  <td className="px-3 py-1.5 tabular-nums text-amber-500/90">{b.price_cache_read_per_1m}</td>
                  <td className="px-3 py-1.5 tabular-nums text-amber-500/90">{b.price_cache_write_per_1m}</td>
                  <td className="px-3 py-1.5 tabular-nums text-[11px] text-[var(--color-muted)]">
                    {b.context_window ?? "–"}
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={b.source === "manual" ? "info" : "ok"}>{b.source}</Badge>
                  </td>
                  <td className="px-3 py-1.5 text-[11px] text-[var(--color-muted)]">
                    {new Date(b.effective_from).toLocaleDateString()}
                    {b.effective_until && (
                      <span className="text-amber-500"> → {new Date(b.effective_until).toLocaleDateString()}</span>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          </div>
        )}
        {model && (
          <div className="mt-2 text-[11px] text-[var(--color-muted)]">
            Showing full history for <span className="font-mono">{model}</span>. Frozen log
            costs never change when bands roll over — each request keeps the band it was
            priced with.
          </div>
        )}
      </Card>

      {manual && (
        <ManualPriceModal
          onClose={() => setManual(false)}
          onSaved={() => { setManual(false); load(model ?? undefined); }}
        />
      )}
    </div>
  );
}

function ManualPriceModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [model, setModel] = useState("");
  const [inP, setInP] = useState("0");
  const [outP, setOutP] = useState("0");
  const [cr, setCr] = useState("0");
  const [cw, setCw] = useState("0");

  return (
    <Modal title="Manual price (wins over fetched maps)" onClose={onClose}>
      <div className="space-y-3">
        <div className="text-[11.5px] text-[var(--color-muted)]">
          Rates are USD per 1M tokens. Local models default to all-zero (still metered).
        </div>
        <Field label="Model name (as seen on the wire)">
          <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="llama3:8b" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Input $/1M"><Input value={inP} onChange={(e) => setInP(e.target.value)} /></Field>
          <Field label="Output $/1M"><Input value={outP} onChange={(e) => setOutP(e.target.value)} /></Field>
          <Field label="Cache read $/1M"><Input value={cr} onChange={(e) => setCr(e.target.value)} /></Field>
          <Field label="Cache write $/1M"><Input value={cw} onChange={(e) => setCw(e.target.value)} /></Field>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!model}
            onClick={async () => {
              await api.post("/admin/prices/manual", {
                model,
                price_in: parseFloat(inP) / 1e6,
                price_out: parseFloat(outP) / 1e6,
                price_cache_read: parseFloat(cr) / 1e6,
                price_cache_write: parseFloat(cw) / 1e6,
              });
              onSaved();
            }}
          >
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
