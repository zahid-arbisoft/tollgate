import { useEffect, useState } from "react";
import { Plug, Plus, Zap } from "lucide-react";
import { api, Provider } from "../api";
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Table } from "../ui";

function ProviderForm({
  initial,
  presets,
  onClose,
  onSaved,
}: {
  initial?: Provider;
  presets: { local: Record<string, { type: string; base_url: string }>; cloud: Record<string, { type: string; base_url: string }> };
  onClose: () => void;
  onSaved: () => void;
}) {
  const [type, setType] = useState(initial?.type ?? "openai");
  const [name, setName] = useState(initial?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [timeoutS, setTimeoutS] = useState(String(initial?.timeout_s ?? 120));
  const [retries, setRetries] = useState(String(initial?.retries ?? 0));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const applyPreset = (presetName: string) => {
    const preset = presets.local[presetName] ?? presets.cloud[presetName];
    if (!preset) return;
    setType(preset.type);
    setName(presetName);
    setBaseUrl(preset.base_url);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const body = {
        type,
        name,
        base_url: baseUrl,
        api_key: apiKey || undefined,
        timeout_s: parseFloat(timeoutS),
        retries: parseInt(retries, 10),
      };
      if (initial) {
        await api.patch(`/admin/providers/${initial.id}`, body);
      } else {
        await api.post("/admin/providers", body);
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "Add provider"} onClose={onClose}>
      <div className="space-y-3">
        {!initial && (
          <div className="flex flex-wrap gap-1.5">
            {Object.keys(presets.cloud).map((p) => (
              <Button key={p} size="xs" onClick={() => applyPreset(p)}>
                {p}
              </Button>
            ))}
            {Object.keys(presets.local).map((p) => (
              <Button key={p} size="xs" variant="ghost" onClick={() => applyPreset(p)}>
                {p} (local)
              </Button>
            ))}
          </div>
        )}
        <Field label="Type">
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="openai-compatible">openai-compatible</option>
            <option value="local">local (keyless)</option>
          </Select>
        </Field>
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="anthropic" />
        </Field>
        <Field label="Base URL">
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.anthropic.com" />
        </Field>
        <Field label={initial ? "Replace API key (empty = keep)" : "API key (empty for local)"}>
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Timeout (s)">
            <Input type="number" value={timeoutS} onChange={(e) => setTimeoutS(e.target.value)} />
          </Field>
          <Field label="Connect retries">
            <Input type="number" value={retries} onChange={(e) => setRetries(e.target.value)} />
          </Field>
        </div>
        {error && <div className="text-[12px] text-red-400">{error}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={busy || !name || !baseUrl} onClick={save}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function Providers() {
  const [providers, setProviders] = useState<Provider[]>([]);
  interface Presets {
    local: Record<string, { type: string; base_url: string }>;
    cloud: Record<string, { type: string; base_url: string }>;
  }
  const [presets, setPresets] = useState<Presets>({ local: {}, cloud: {} });
  const [editing, setEditing] = useState<Provider | "new" | null>(null);
  const [tests, setTests] = useState<Record<number, string>>({});

  const load = async () => {
    const [p, presetData] = await Promise.all([
      api.get<Provider[]>("/admin/providers"),
      api.get<Presets>("/admin/providers/presets"),
    ]);
    setProviders(p);
    setPresets(presetData);
  };
  useEffect(() => {
    load();
    const timer = setInterval(load, 15_000);
    return () => clearInterval(timer);
  }, []);

  const test = async (id: number) => {
    setTests({ ...tests, [id]: "…" });
    const result = await api.post<{ ok: boolean; status_code?: number; latency_ms?: number; error?: string }>(
      `/admin/providers/${id}/test`,
    );
    setTests({
      ...tests,
      [id]: result.ok
        ? `ok (${result.status_code}, ${result.latency_ms} ms)`
        : `failed: ${result.error ?? result.status_code}`,
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Providers</h1>
        <Button variant="primary" onClick={() => setEditing("new")}>
          <Plug size={13} /> Add provider
        </Button>
      </div>

      <Card title={`${providers.length} upstreams`}>
        {providers.length === 0 ? (
          <Empty>
            No providers. Add Anthropic / OpenAI / any OpenAI-compatible endpoint, or a local
            preset (Ollama, MLX, LM Studio…).
          </Empty>
        ) : (
          <Table head={["Name", "Type", "Base URL", "Key", "Timeout", "Status", "Actions"]}>
            {providers.map((p) => (
              <tr key={p.id} className="hover:bg-zinc-900/40">
                <td className="px-3 py-2 font-medium">{p.name}</td>
                <td className="px-3 py-2 text-[var(--color-muted)]">{p.type}</td>
                <td className="px-3 py-2 font-mono text-[11px]">{p.base_url}</td>
                <td className="px-3 py-2">
                  {p.type === "local" ? (
                    <span className="text-[11px] text-[var(--color-muted)]">keyless</span>
                  ) : (
                    <Badge tone={p.has_key ? "ok" : "warn"}>{p.has_key ? "set" : "missing"}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 tabular-nums text-[11px]">{p.timeout_s}s</td>
                <td className="px-3 py-2">
                  <Badge tone={p.enabled ? "active" : "disabled"}>{p.enabled ? "enabled" : "off"}</Badge>
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <Button size="xs" onClick={() => test(p.id)}>
                      <Zap size={11} /> Test
                    </Button>
                    <Button size="xs" onClick={() => setEditing(p)}>Edit</Button>
                    <Button
                      size="xs"
                      onClick={async () => {
                        await api.patch(`/admin/providers/${p.id}`, { enabled: !p.enabled });
                        load();
                      }}
                    >
                      {p.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      size="xs"
                      variant="danger"
                      onClick={async () => {
                        await api.del(`/admin/providers/${p.id}`);
                        load();
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                  {tests[p.id] && (
                    <div className={`mt-1 text-[10px] ${tests[p.id].startsWith("ok") ? "text-emerald-400" : "text-red-400"}`}>
                      {tests[p.id]}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {editing && (
        <ProviderForm
          initial={editing === "new" ? undefined : editing}
          presets={presets}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
