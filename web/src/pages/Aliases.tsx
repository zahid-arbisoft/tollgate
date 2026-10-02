import { useEffect, useState } from "react";
import { Plus, ArrowUpDown } from "lucide-react";
import { api, Alias, Provider } from "../api";
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Table } from "../ui";

interface Fallback {
  provider_id: number;
  upstream_model: string;
}

function AliasForm({
  initial,
  providers,
  onClose,
  onSaved,
}: {
  initial?: Alias;
  providers: Provider[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [aliasName, setAliasName] = useState(initial?.alias_name ?? "");
  const [providerId, setProviderId] = useState(initial?.provider_id ?? providers[0]?.id);
  const [upstreamModel, setUpstreamModel] = useState(initial?.upstream_model ?? "");
  const [fallbacks, setFallbacks] = useState<Fallback[]>(initial?.fallbacks ?? []);

  const providerName = (id: number) => providers.find((p) => p.id === id)?.name ?? id;

  const save = async () => {
    const body = {
      alias_name: aliasName,
      provider_id: providerId,
      upstream_model: upstreamModel,
      fallbacks,
      enabled: initial?.enabled ?? true,
    };
    if (initial) await api.patch(`/admin/aliases/${initial.id}`, body);
    else await api.post("/admin/aliases", body);
    onSaved();
    onClose();
  };

  return (
    <Modal title={initial ? `Edit ${initial.alias_name}` : "Add alias"} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Alias (the name your projects call)">
          <Input value={aliasName} onChange={(e) => setAliasName(e.target.value)} placeholder="model-a" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Primary provider">
            <Select value={providerId} onChange={(e) => setProviderId(parseInt(e.target.value, 10))}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Upstream model">
            <Input value={upstreamModel} onChange={(e) => setUpstreamModel(e.target.value)} placeholder="claude-sonnet-4-5" />
          </Field>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-muted)]">
              Fallback chain (tried in order on transport/5xx errors)
            </div>
            <Button
              size="xs"
              onClick={() =>
                setFallbacks([...fallbacks, { provider_id: providers[0]?.id, upstream_model: upstreamModel }])
              }
            >
              <Plus size={11} /> hop
            </Button>
          </div>
          <div className="space-y-1.5">
            {fallbacks.map((f, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-5 text-center text-[11px] text-[var(--color-muted)]">{i + 1}</span>
                <Select
                  value={f.provider_id}
                  onChange={(e) =>
                    setFallbacks(
                      fallbacks.map((x, j) =>
                        j === i ? { ...x, provider_id: parseInt(e.target.value, 10) } : x,
                      ),
                    )
                  }
                >
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                <Input
                  value={f.upstream_model}
                  onChange={(e) =>
                    setFallbacks(fallbacks.map((x, j) => (j === i ? { ...x, upstream_model: e.target.value } : x)))
                  }
                />
                <div className="flex flex-col">
                  <Button size="xs" variant="ghost" disabled={i === 0} onClick={() => {
                    const copy = [...fallbacks];
                    [copy[i - 1], copy[i]] = [copy[i], copy[i - 1]];
                    setFallbacks(copy);
                  }}>↑</Button>
                  <Button size="xs" variant="ghost" onClick={() => setFallbacks(fallbacks.filter((_, j) => j !== i))}>
                    ✕
                  </Button>
                </div>
              </div>
            ))}
            {fallbacks.length === 0 && (
              <div className="text-[11px] text-[var(--color-muted)]">No fallbacks — primary only.</div>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!aliasName || !upstreamModel} onClick={save}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function Aliases() {
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [editing, setEditing] = useState<Alias | "new" | null>(null);

  const load = async () => {
    const [a, p] = await Promise.all([
      api.get<Alias[]>("/admin/aliases"),
      api.get<Provider[]>("/admin/providers"),
    ]);
    setAliases(a);
    setProviders(p);
  };
  useEffect(() => {
    load();
    const timer = setInterval(load, 15_000);
    return () => clearInterval(timer);
  }, []);

  const providerName = (id: number) => providers.find((p) => p.id === id)?.name ?? String(id);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Aliases & routing</h1>
        <Button variant="primary" disabled={providers.length === 0} onClick={() => setEditing("new")}>
          <Plus size={13} /> Add alias
        </Button>
      </div>

      <Card title={`${aliases.length} aliases`}>
        {aliases.length === 0 ? (
          <Empty>
            Aliases map a stable model name to (provider, upstream model) with an ordered
            fallback chain — point a benchmark suite at <code>model-a</code> and swap the
            backend without touching the suite.
          </Empty>
        ) : (
          <Table head={["Alias", "Primary", "Fallback chain", "Status", "Actions"]}>
            {aliases.map((a) => (
              <tr key={a.id} className="hover:bg-zinc-900/40">
                <td className="px-3 py-2 font-mono">{a.alias_name}</td>
                <td className="px-3 py-2">
                  {providerName(a.provider_id)} → <span className="font-mono text-[11px]">{a.upstream_model}</span>
                </td>
                <td className="px-3 py-2 text-[11px] text-[var(--color-muted)]">
                  {a.fallbacks.length === 0 ? (
                    "–"
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      <ArrowUpDown size={11} />
                      {a.fallbacks.map((f) => `${providerName(f.provider_id)}/${f.upstream_model}`).join(" → ")}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Badge tone={a.enabled ? "active" : "disabled"}>{a.enabled ? "on" : "off"}</Badge>
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <Button size="xs" onClick={() => setEditing(a)}>Edit</Button>
                    <Button
                      size="xs"
                      onClick={async () => {
                        await api.patch(`/admin/aliases/${a.id}`, { enabled: !a.enabled });
                        load();
                      }}
                    >
                      {a.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      size="xs"
                      variant="danger"
                      onClick={async () => {
                        await api.del(`/admin/aliases/${a.id}`);
                        load();
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {editing && (
        <AliasForm
          initial={editing === "new" ? undefined : editing}
          providers={providers}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
