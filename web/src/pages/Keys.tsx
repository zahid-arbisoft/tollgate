import { useEffect, useState } from "react";
import { Copy, KeyRound, Plus, RotateCcw } from "lucide-react";
import {
  api,
  fmtNum,
  fmtTime,
  fmtUsd,
  LimitRule,
  VirtualKey,
} from "../api";
import { useScope } from "../scope";
import {
  Badge,
  Button,
  Card,
  Empty,
  Field,
  Input,
  Modal,
  Select,
  Table,
} from "../ui";

function PlaintextOnce({ plaintext, onClose }: { plaintext: string; onClose: () => void }) {
  return (
    <Modal title="Virtual key created" onClose={onClose}>
      <div className="mb-3 text-[12px] text-amber-400">
        Shown once — store it now. It is not kept on the server.
      </div>
      <div className="flex items-center gap-2 rounded-md border border-[var(--color-line)] bg-zinc-900 px-3 py-2">
        <code className="flex-1 break-all text-[12px]">{plaintext}</code>
        <Button
          size="xs"
          onClick={() => navigator.clipboard.writeText(plaintext)}
        >
          <Copy size={12} /> Copy
        </Button>
      </div>
    </Modal>
  );
}

function CreateKeyWizard({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (k: VirtualKey) => void;
}) {
  const scope = useScope();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [project, setProject] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("");
  const [allowedProviders, setAllowedProviders] = useState<string[]>([]);
  const [allowedModels, setAllowedModels] = useState("");
  const [limits, setLimits] = useState<{ metric: string; window: string; value: string; auto_block: boolean }[]>([]);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const key = await api.post<VirtualKey>("/admin/keys", {
        name,
        project: project || null,
        expires_in_days: expiresInDays ? parseInt(expiresInDays, 10) : null,
        allowed_providers: allowedProviders.length ? allowedProviders : null,
        allowed_models_aliases: allowedModels
          ? allowedModels.split(",").map((s) => s.trim()).filter(Boolean)
          : null,
      });
      for (const l of limits) {
        await api.post("/admin/limits", {
          key_id: key.id,
          metric: l.metric,
          window: l.window,
          value: parseFloat(l.value),
          auto_block: l.auto_block,
        });
      }
      onCreated(key);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Create virtual key" onClose={onClose}>
      {step === 1 && (
        <div className="space-y-3">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-project" />
          </Field>
          <Field label="Project / tag">
            <Input value={project} onChange={(e) => setProject(e.target.value)} placeholder="optional" />
          </Field>
          <Field label="Expires in (days)">
            <Input
              value={expiresInDays}
              onChange={(e) => setExpiresInDays(e.target.value)}
              placeholder="never"
              type="number"
            />
          </Field>
          <Field label="Allowed providers (none checked = all)">
            <div className="max-h-36 space-y-1 overflow-y-auto rounded-md border border-[var(--color-line)] bg-zinc-900/40 p-2">
              {scope.providers.length === 0 && (
                <div className="text-[11px] text-[var(--color-muted)]">
                  No providers configured — key will allow all.
                </div>
              )}
              {scope.providers.map((p) => (
                <label key={p.id} className="flex items-center gap-2 text-[12px]">
                  <input
                    type="checkbox"
                    checked={allowedProviders.includes(p.name)}
                    onChange={(e) =>
                      setAllowedProviders(
                        e.target.checked
                          ? [...allowedProviders, p.name]
                          : allowedProviders.filter((n) => n !== p.name),
                      )
                    }
                  />
                  {p.name}
                  <span className="text-[10px] text-[var(--color-muted)]">({p.type})</span>
                </label>
              ))}
            </div>
          </Field>
          <Field label="Allowed models / aliases">
            <Input value={allowedModels} onChange={(e) => setAllowedModels(e.target.value)} placeholder="empty = all" />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="primary" onClick={() => setStep(2)}>
              Next: limits
            </Button>
          </div>
        </div>
      )}
      {step === 2 && (
        <div className="space-y-3">
          {limits.length === 0 && (
            <div className="text-[12px] text-[var(--color-muted)]">
              No limits — the key is unrestricted. Add one or more:
            </div>
          )}
          {limits.map((l, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_100px_28px] items-center gap-2">
              <Select
                value={l.metric}
                onChange={(e) =>
                  setLimits(limits.map((x, j) => (j === i ? { ...x, metric: e.target.value } : x)))
                }
              >
                {["requests", "tokens_in", "tokens_out", "tokens_total", "cost_usd"].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </Select>
              <Select
                value={l.window}
                onChange={(e) =>
                  setLimits(limits.map((x, j) => (j === i ? { ...x, window: e.target.value } : x)))
                }
              >
                {["minute", "hour", "day", "month", "total"].map((w) => (
                  <option key={w}>{w}</option>
                ))}
              </Select>
              <Input
                value={l.value}
                type="number"
                placeholder="value"
                onChange={(e) =>
                  setLimits(limits.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                }
              />
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setLimits(limits.filter((_, j) => j !== i))}
              >
                ✕
              </Button>
            </div>
          ))}
          <label className="flex items-center gap-2 text-[12px] text-[var(--color-muted)]">
            <input
              type="checkbox"
              checked={limits.length > 0 && limits.every((l) => l.auto_block)}
              onChange={(e) => setLimits(limits.map((l) => ({ ...l, auto_block: e.target.checked })))}
            />
            auto-block key on breach
          </label>
          <div className="flex items-center justify-between pt-2">
            <Button
              size="xs"
              onClick={() => setLimits([...limits, { metric: "cost_usd", window: "day", value: "", auto_block: true }])}
            >
              <Plus size={12} /> Add limit
            </Button>
            <div className="flex gap-2">
              <Button onClick={() => setStep(1)}>Back</Button>
              <Button variant="primary" disabled={busy} onClick={create}>
                Create key
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

export default function Keys() {
  const [keys, setKeys] = useState<VirtualKey[]>([]);
  const [limits, setLimits] = useState<LimitRule[]>([]);
  const [creating, setCreating] = useState(false);
  const [fresh, setFresh] = useState<VirtualKey | null>(null);
  const [drill, setDrill] = useState<VirtualKey | null>(null);

  const load = async () => {
    try {
      const [k, l] = await Promise.all([
        api.get<VirtualKey[]>("/admin/keys"),
        api.get<LimitRule[]>("/admin/limits"),
      ]);
      setKeys(k);
      setLimits(l);
    } catch {
      /* offline banner handles it */
    }
  };
  useEffect(() => {
    load();
    const timer = setInterval(load, 15_000); // see rows synced from peers
    return () => clearInterval(timer);
  }, []);

  const act = async (id: string, action: string, body?: unknown) => {
    await api.post(`/admin/keys/${id}/${action}`, body);
    await load();
  };

  const rotate = async (id: string) => {
    const rotated = await api.post<VirtualKey>(`/admin/keys/${id}/rotate`);
    await load();
    setFresh(rotated);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Virtual keys</h1>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <KeyRound size={13} /> Create key
        </Button>
      </div>

      <Card title={`${keys.length} keys`}>
        {keys.length === 0 ? (
          <Empty>
            No keys yet — create one and point your project at Tollgate with
            base URL <code>http://127.0.0.1:8787</code>.
          </Empty>
        ) : (
          <Table head={["Key", "Status", "Limits", "Created", "Expires", "Actions"]}>
            {keys.map((k) => {
              const klimits = limits.filter((l) => l.key_id === k.id);
              return (
                <tr key={k.id} className="hover:bg-zinc-900/40">
                  <td className="px-3 py-2">
                    <button className="text-left" onClick={() => setDrill(k)}>
                      <div className="font-mono text-[12px]">{k.prefix}…</div>
                      <div className="text-[11px] text-[var(--color-muted)]">
                        {k.name || "unnamed"}
                        {k.project ? ` · ${k.project}` : ""}
                      </div>
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={k.status}>{k.status}</Badge>
                    {k.blocked_reason && (
                      <div className="mt-0.5 text-[10px] text-red-400">{k.blocked_reason}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[11px] text-[var(--color-muted)]">
                    {klimits.length === 0
                      ? "–"
                      : klimits
                          .map((l) => `${l.metric}/${l.window}: ${fmtNum(l.value)}${l.auto_block ? " ⛔" : ""}`)
                          .join(", ")}
                  </td>
                  <td className="px-3 py-2 text-[11px] text-[var(--color-muted)]">
                    {fmtTime(k.created_at)}
                  </td>
                  <td className="px-3 py-2 text-[11px] text-[var(--color-muted)]">
                    {k.expires_at ? fmtTime(k.expires_at) : "never"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {k.status === "active" ? (
                        <Button size="xs" onClick={() => act(k.id, "disable")}>Disable</Button>
                      ) : (
                        <Button size="xs" onClick={() => act(k.id, "enable")}>Enable</Button>
                      )}
                      {k.status === "blocked" ? (
                        <Button size="xs" variant="primary" onClick={() => act(k.id, "unblock")}>Unblock</Button>
                      ) : (
                        <Button size="xs" onClick={() => act(k.id, "block")}>Block</Button>
                      )}
                      <Button size="xs" onClick={() => rotate(k.id)}>
                        <RotateCcw size={11} /> Rotate
                      </Button>
                      <Button size="xs" onClick={() => act(k.id, "extend", { days: 30 })}>
                        +30d
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      {creating && (
        <CreateKeyWizard
          onClose={() => setCreating(false)}
          onCreated={(k) => {
            setCreating(false);
            setFresh(k);
            load();
          }}
        />
      )}
      {fresh && (
        <PlaintextOnce plaintext={fresh.plaintext!} onClose={() => setFresh(null)} />
      )}

      {drill && (
        <Modal
          title={`Key ${drill.prefix}… ${drill.name ? `· ${drill.name}` : ""}`}
          onClose={() => setDrill(null)}
          wide
        >
          <KeyDrill keyId={drill.id} />
        </Modal>
      )}
    </div>
  );
}

function KeyDrill({ keyId }: { keyId: string }) {
  interface KeyStats {
    summary: { requests: number; tokens_in: number; tokens_out: number; cost_usd: number };
    series: { bucket: string; requests: number; cost_usd: number }[];
  }
  const [stats, setStats] = useState<KeyStats | null>(null);

  useEffect(() => {
    const days = 30;
    const from = new Date(Date.now() - days * 86400_000).toISOString();
    api
      .get<KeyStats>(`/admin/stats?key_id=${keyId}&from=${from}&granularity=day`)
      .then(setStats);
  }, [keyId]);

  if (!stats) return <Empty>Loading…</Empty>;
  const s = stats.summary;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2 text-center">
        {[
          ["Requests", fmtNum(s.requests)],
          ["Tokens in", fmtNum(s.tokens_in)],
          ["Tokens out", fmtNum(s.tokens_out)],
          ["Cost (30d)", fmtUsd(s.cost_usd)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-md border border-[var(--color-line)] px-2 py-2">
            <div className="text-[10px] uppercase text-[var(--color-muted)]">{label}</div>
            <div className="text-[15px] font-semibold tabular-nums">{value}</div>
          </div>
        ))}
      </div>
      <div className="rounded-md border border-[var(--color-line)] p-3 text-[11.5px] text-[var(--color-muted)]">
        Daily series (chart in Logs view):{" "}
        {stats.series.map((p) => `${p.bucket}: ${p.requests} req / ${fmtUsd(p.cost_usd)}`).join(" · ") || "no usage yet"}
      </div>
    </div>
  );
}
