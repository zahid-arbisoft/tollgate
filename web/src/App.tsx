import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import {
  Activity,
  KeyRound,
  Radio,
  ScrollText,
  Plug,
  Tags,
  DollarSign,
  Settings as SettingsIcon,
  TowerControl,
} from "lucide-react";
import { api, getToken, setToken } from "./api";
import { ScopeProvider } from "./scope";
import { Button, Input } from "./ui";
import Overview from "./pages/Overview";
import Live from "./pages/Live";
import Keys from "./pages/Keys";
import Logs from "./pages/Logs";
import Providers from "./pages/Providers";
import Pricing from "./pages/Pricing";
import Aliases from "./pages/Aliases";
import Settings from "./pages/Settings";
import Sync from "./pages/Sync";

const NAV = [
  { to: "/", label: "Overview", icon: Activity },
  { to: "/keys", label: "Keys", icon: KeyRound },
  { to: "/live", label: "Live", icon: Radio },
  { to: "/logs", label: "Logs", icon: ScrollText },
  { to: "/providers", label: "Providers", icon: Plug },
  { to: "/pricing", label: "Pricing", icon: DollarSign },
  { to: "/aliases", label: "Aliases", icon: Tags },
  { to: "/sync", label: "Sync", icon: TowerControl },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function TokenGate({ onOk }: { onOk: () => void }) {
  const [token, setTok] = useState(getToken());
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const submit = async () => {
    setChecking(true);
    setError("");
    try {
      setToken(token.trim(), remember ? 30 : 0);
      await api.get("/admin/settings");
      onOk();
    } catch {
      setError("Invalid admin token");
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-80 rounded-xl border border-[var(--color-line)] bg-[var(--color-panel)] p-6">
        <div className="mb-1 text-lg font-semibold">Tollgate</div>
        <div className="mb-4 text-[12px] text-[var(--color-muted)]">
          Enter the admin token to open the dashboard. Find it with{" "}
          <code className="rounded bg-zinc-800 px-1">tollgate key admin-token</code>{" "}
          or in the secrets store.
        </div>
        <Input
          type="password"
          placeholder="admin token"
          value={token}
          onChange={(e) => setTok(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        {error && <div className="mt-2 text-[12px] text-red-400">{error}</div>}
        <label className="mt-3 flex items-center gap-2 text-[12px] text-[var(--color-muted)]">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          Stay signed in for 30 days on this device
        </label>
        <Button
          variant="primary"
          className="mt-4 w-full justify-center"
          disabled={checking}
          onClick={submit}
        >
          {checking ? "Checking…" : "Unlock dashboard"}
        </Button>
      </div>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [serverUp, setServerUp] = useState(true);
  const location = useLocation();

  useEffect(() => {
    const onConn = (e: Event) =>
      setServerUp((e as CustomEvent<{ up: boolean }>).detail.up);
    window.addEventListener("tollgate-conn", onConn as EventListener);
    return () => window.removeEventListener("tollgate-conn", onConn as EventListener);
  }, []);

  useEffect(() => {
    if (!getToken()) {
      setAuthed(false);
      return;
    }
    api
      .get("/admin/settings")
      .then(() => setAuthed(true))
      .catch((e) => setAuthed(e.status === 401 ? false : true));
  }, []);

  if (authed === null) {
    return <div className="p-8 text-[var(--color-muted)]">Loading…</div>;
  }
  if (!authed) {
    return <TokenGate onOk={() => setAuthed(true)} />;
  }

  return (
    <ScopeProvider>
      <div className="flex h-full">
        {!serverUp && (
          <div className="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-2 border-b border-red-500/40 bg-red-500/15 px-4 py-2 text-[12.5px] text-red-300 backdrop-blur">
            <span className="h-2 w-2 animate-pulse rounded-full bg-red-400" />
            Cannot reach the Tollgate server — is{" "}
            <code className="rounded bg-red-500/20 px-1">uv run tollgate serve</code>{" "}
            running? Waiting for it to come back…
          </div>
        )}
        <aside className="flex w-48 shrink-0 flex-col border-r border-[var(--color-line)] bg-[var(--color-panel)]">
          <div className="flex items-center gap-2 px-4 py-4">
            <TowerControl size={18} className="text-[var(--color-accent)]" />
            <span className="text-[15px] font-semibold tracking-tight">
              Tollgate
            </span>
          </div>
          <nav className="flex-1 space-y-0.5 px-2">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors ${
                    isActive
                      ? "bg-indigo-500/15 text-indigo-300"
                      : "text-[var(--color-muted)] hover:bg-zinc-800/50 hover:text-zinc-200"
                  }`
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="px-4 py-3 text-[10px] text-zinc-600">
            local-first LLM gateway
          </div>
        </aside>
        <main className="flex-1 overflow-y-auto">
          <div
            key={location.pathname}
            className="mx-auto max-w-6xl px-6 py-5"
          >
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/live" element={<Live />} />
              <Route path="/keys" element={<Keys />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/providers" element={<Providers />} />
              <Route path="/pricing" element={<Pricing />} />
              <Route path="/aliases" element={<Aliases />} />
              <Route path="/sync" element={<Sync />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </main>
      </div>
    </ScopeProvider>
  );
}
