import { useEffect, useState } from "react";
import { api, getToken, setToken } from "../api";
import { Badge, Button, Card, Field, Input } from "../ui";

interface AppSettings {
  version: string;
  retention_days: number;
  log_bodies: boolean;
  webhook_url: string;
  host: string;
  port: number;
  instance_id: string;
  secrets_backend: string;
  data_dir: string;
}

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [retention, setRetention] = useState("");
  const [webhook, setWebhook] = useState("");
  const [logBodies, setLogBodies] = useState(false);
  const [saved, setSaved] = useState("");
  const [backups, setBackups] = useState<string[]>([]);
  const [token, setTok] = useState(getToken());
  const [update, setUpdate] = useState<string>("");

  const load = async () => {
    const s = await api.get<AppSettings>("/admin/settings");
    setSettings(s);
    setRetention(String(s.retention_days));
    setWebhook(s.webhook_url || "");
    setLogBodies(s.log_bodies);
    setBackups(await api.get<string[]>("/admin/backups"));
  };
  useEffect(() => {
    load();
  }, []);

  if (!settings) return null;

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Settings</h1>

      <Card title="General">
        <div className="grid max-w-lg gap-3">
          <Field label="Log retention (days)">
            <Input type="number" value={retention} onChange={(e) => setRetention(e.target.value)} />
          </Field>
          <Field label="Warn/breach webhook URL (optional)">
            <Input
              value={webhook}
              onChange={(e) => setWebhook(e.target.value)}
              placeholder="https://hooks.slack.com/… (POSTed JSON on limit warn/breach)"
            />
          </Field>
          <label className="flex items-center gap-2 text-[12px]">
            <input
              type="checkbox"
              checked={logBodies}
              onChange={(e) => setLogBodies(e.target.checked)}
            />
            Store redacted request/response previews (off = maximum privacy)
          </label>
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              onClick={async () => {
                await api.put("/admin/settings", {
                  retention_days: parseInt(retention, 10),
                  webhook_url: webhook || "",
                  log_bodies: logBodies,
                });
                setSaved("Saved.");
                setTimeout(() => setSaved(""), 1500);
              }}
            >
              Save
            </Button>
            {saved && <span className="text-[12px] text-emerald-400">{saved}</span>}
          </div>
        </div>
      </Card>

      <Card
        title="Updates"
        right={
          <Button
            onClick={async () => {
              setUpdate("checking…");
              try {
                const r = await api.get<{ enabled: boolean; current: string; latest?: string; up_to_date?: boolean; error?: string }>(
                  "/admin/update-check",
                );
                setUpdate(
                  r.enabled
                    ? r.error
                      ? `check failed: ${r.error}`
                      : r.up_to_date
                        ? `up to date (${r.current})`
                        : `update available: ${r.current} → ${r.latest}`
                    : "update checks disabled (set update_manifest_url)",
                );
              } catch (e) {
                setUpdate(String((e as Error).message));
              }
            }}
          >
            Check for updates
          </Button>
        }
      >
        <div className="text-[12px] text-[var(--color-muted)]">
          {update || "Compares against latest.json from your release manifest (opt-in)."}
        </div>
      </Card>

      <Card title="This instance">
        <div className="grid grid-cols-2 gap-2 text-[12px]">
          {[
            ["Version", settings.version],
            ["Instance id", settings.instance_id],
            ["Binding", `${settings.host}:${settings.port} (localhost by default)`],
            ["Secrets backend", settings.secrets_backend],
            ["Data directory", settings.data_dir],
            ["Body previews", settings.log_bodies ? "ON" : "off (default)"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-md border border-[var(--color-line)] px-2.5 py-1.5">
              <div className="text-[10px] uppercase text-[var(--color-muted)]">{label}</div>
              <div className="mt-0.5 font-mono text-[11.5px]">{value}</div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Dashboard admin token">
        <div className="flex max-w-lg items-center gap-2">
          <Input type="password" value={token} onChange={(e) => setTok(e.target.value)} />
          <Button
            onClick={() => {
              setToken(token.trim(), 30);
              setSaved("Token updated.");
              setTimeout(() => setSaved(""), 1500);
            }}
          >
            Use token
          </Button>
        </div>
      </Card>

      <Card
        title="Backups"
        right={
          <Button
            onClick={async () => {
              await api.post("/admin/backup");
              load();
            }}
          >
            Snapshot now
          </Button>
        }
      >
        {backups.length === 0 ? (
          <div className="text-[12px] text-[var(--color-muted)]">
            No backups yet. A snapshot checkpoints the DB (WAL truncated) and copies the file
            into the data directory.
          </div>
        ) : (
          <div className="space-y-1">
            {backups.map((b) => (
              <div key={b} className="flex items-center justify-between rounded border border-[var(--color-line)] px-3 py-1.5 text-[12px]">
                <span className="font-mono text-[11px]">{b}</span>
                <div className="flex items-center gap-2">
                  <Badge tone="info">file</Badge>
                  <Button
                    size="xs"
                    onClick={async () => {
                      await api.post(`/admin/backups/${b}/restore`);
                      alert("Restored — restart Tollgate to use the restored database.");
                    }}
                  >
                    Restore
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
