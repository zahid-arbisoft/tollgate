// Global scope selector (plan §10): applied to every stats/logs view.
// All keys ⇄ one key · provider · model · machine (merged ⇄ this machine).

import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
import { api, VirtualKey, Provider, Alias } from "./api";
import { Select } from "./ui";

export type Range = "today" | "7d" | "30d" | "90d";

interface ScopeState {
  keyId: string; // "" = all
  provider: string; // "" = all
  model: string; // "" = all
  instanceId: string; // "" = all machines (merged)
  granularity: "hour" | "day" | "month";
  range: Range;
  keys: VirtualKey[];
  providers: Provider[];
  aliases: Alias[];
  instances: { instance_id: string; requests: number }[];
  models: string[];
  set: (patch: Partial<ScopeState>) => void;
  scopeQuery: () => string;
}

const Ctx = createContext<ScopeState>(null as unknown as ScopeState);

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState({
    keyId: "",
    provider: "",
    model: "",
    instanceId: "",
    granularity: "day" as ScopeState["granularity"],
    range: "7d" as Range,
    keys: [] as VirtualKey[],
    providers: [] as Provider[],
    aliases: [] as Alias[],
    instances: [] as ScopeState["instances"],
    models: [] as string[],
  });

  const load = async () => {
    try {
      const [keys, providers, aliases, instances] = await Promise.all([
        api.get<VirtualKey[]>("/admin/keys"),
        api.get<Provider[]>("/admin/providers"),
        api.get<Alias[]>("/admin/aliases"),
        api.get<{ instance_id: string; requests: number }[]>("/admin/instances"),
      ]);
      const models = Array.from(
        new Set([
          ...aliases.map((a) => a.alias_name),
          ...aliases.map((a) => a.upstream_model),
        ]),
      ).sort();
      setState((s) => ({
        ...s,
        keys,
        providers,
        aliases,
        instances,
        models,
      }));
    } catch {
      /* unauthenticated — App shows the token gate */
    }
  };

  useEffect(() => {
    load();
    // Dropdowns must see newly created/synced keys, providers, aliases and
    // machines without an app restart.
    const timer = setInterval(load, 15_000);
    return () => clearInterval(timer);
  }, []);

  const set = (patch: Partial<ScopeState>) =>
    setState((s) => ({ ...s, ...patch }));

  const scopeQuery = () => {
    const p = new URLSearchParams();
    if (state.keyId) p.set("key_id", state.keyId);
    if (state.provider) p.set("provider", state.provider);
    if (state.model) p.set("model", state.model);
    if (state.instanceId) p.set("instance_id", state.instanceId);
    const days =
      state.range === "today" ? 1 : parseInt(state.range.replace("d", ""), 10);
    const from = new Date(Date.now() - days * 86400_000).toISOString();
    p.set("from", from);
    p.set("granularity", state.granularity);
    return p.toString();
  };

  return (
    <Ctx.Provider value={{ ...state, set, scopeQuery }}>{children}</Ctx.Provider>
  );
}

export function useScope() {
  return useContext(Ctx);
}

export function ScopeBar() {
  const s = useScope();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={s.keyId}
        onChange={(e) => s.set({ keyId: e.target.value })}
        title="Key"
      >
        <option value="">All keys</option>
        {s.keys.map((k) => (
          <option key={k.id} value={k.id}>
            {k.name || k.prefix}
          </option>
        ))}
      </Select>
      <Select
        value={s.provider}
        onChange={(e) => s.set({ provider: e.target.value })}
        title="Provider"
      >
        <option value="">All providers</option>
        {s.providers.map((p) => (
          <option key={p.id} value={p.name}>
            {p.name}
          </option>
        ))}
      </Select>
      <Select
        value={s.model}
        onChange={(e) => s.set({ model: e.target.value })}
        title="Model / alias"
      >
        <option value="">All models</option>
        {s.models.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </Select>
      <Select
        value={s.instanceId}
        onChange={(e) => s.set({ instanceId: e.target.value })}
        title="Machine"
      >
        <option value="">All machines (merged)</option>
        {s.instances.map((i) => (
          <option key={i.instance_id} value={i.instance_id}>
            {i.instance_id === i.instance_id ? `machine ${i.instance_id.slice(0, 8)}` : ""}
          </option>
        ))}
      </Select>
      <div className="mx-1 h-4 w-px bg-[var(--color-line)]" />
      <Select
        value={s.range}
        onChange={(e) => s.set({ range: e.target.value as Range })}
      >
        <option value="today">Today</option>
        <option value="7d">7 days</option>
        <option value="30d">30 days</option>
        <option value="90d">90 days</option>
      </Select>
      <Select
        value={s.granularity}
        onChange={(e) =>
          s.set({ granularity: e.target.value as ScopeState["granularity"] })
        }
      >
        <option value="hour">hourly</option>
        <option value="day">daily</option>
        <option value="month">monthly</option>
      </Select>
    </div>
  );
}
