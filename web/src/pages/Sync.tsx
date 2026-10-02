import { useEffect, useState } from "react";
import { FileDown, FileUp, Plus, RefreshCw, TowerControl } from "lucide-react";
import { api, fmtTime } from "../api";
import { Badge, Button, Card, Empty, Field, Input, Modal, Table } from "../ui";

interface PeerRow {
  id: number;
  name: string;
  endpoint_url: string;
  enabled: boolean;
  last_seen: string | null;
  last_sent_cursor: string;
  last_received_cursor: string;
  last_error: string | null;
}

interface AuditRow {
  id: string;
  ts: string;
  entity: string;
  row_pk: string;
  op: string;
  origin_instance: string;
}

function AddPeerModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [generated, setGenerated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.post<PeerRow & { shared_token: string }>("/admin/peers", {
        name,
        endpoint_url: url,
        shared_token: token || undefined,
        enabled,
      });
      setGenerated(result.shared_token);
      onSaved();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  if (generated) {
    return (
      <Modal title="Peer paired" onClose={onClose}>
        <div className="space-y-3">
          <div className="text-[12px]">
            Pairing token (shown once): share it with the other machine — it goes into
            its "Add peer" form together with <b>this machine's URL</b>.
          </div>
          <div className="flex items-center gap-2 rounded-md border border-[var(--color-line)] bg-zinc-900 px-3 py-2">
            <code className="flex-1 break-all text-[12px]">{generated}</code>
            <Button size="xs" onClick={() => navigator.clipboard.writeText(generated)}>
              Copy
            </Button>
          </div>
          <Button variant="primary" className="w-full justify-center" onClick={onClose}>
            Done
          </Button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Add peer" onClose={onClose}>
      <div className="space-y-3">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="windows-laptop" />
        </Field>
        <Field label="Peer URL (its Tollgate address)">
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://192.168.1.31:8787" />
        </Field>
        <Field label="Shared pairing token (paste the one the peer generated — empty = generate new)">
          <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-[12px]">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          Active (uncheck if this machine never dials the peer — e.g. behind a
          one-way network like a VM slirp link; the entry then only authenticates
          the peer's incoming sync)
        </label>
        {error && <div className="text-[12px] text-red-400">{error}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={busy || !name || !url} onClick={save}>
            Pair
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function Sync() {
  const [state, setState] = useState<{ peers: PeerRow[]; audit: AuditRow[] } | null>(null);
  const [adding, setAdding] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [fileBusy, setFileBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [me, setMe] = useState("");

  const load = async () => {
    try {
      setState(await api.get("/admin/sync/state"));
    } catch {
      /* offline banner handles it */
    }
  };
  useEffect(() => {
    const tick = () => {
      load();
      api
        .get<{ instance_id: string }>("/admin/settings")
        .then((s) => setMe(s.instance_id))
        .catch(() => {});
    };
    tick();
    const timer = setInterval(tick, 15_000); // cursors/last_seen/audit live-update
    return () => clearInterval(timer);
  }, []);

  const syncNow = async () => {
    setSyncing(true);
    setMessage("");
    try {
      const results = await api.post<
        { peer: string; pushed: number; pulled: number; error: string | null }[]
      >("/admin/sync/run");
      setMessage(
        results
          .map((r) =>
            r.error ? `${r.peer}: error — ${r.error}` : `${r.peer}: +${r.pulled} in / ${r.pushed} out`,
          )
          .join(" · ") || "no peers configured",
      );
      await load();
    } finally {
      setSyncing(false);
    }
  };

  const exportFile = async () => {
    setFileBusy(true);
    try {
      const path = prompt("Export sync file to (path on this machine):", "tollgate-sync.json");
      if (!path) return;
      const r = await api.post<{ written: number }>("/admin/sync/export", { path });
      setMessage(`exported ${r.written} events → ${path}`);
    } finally {
      setFileBusy(false);
    }
  };

  const importFile = async () => {
    setFileBusy(true);
    try {
      const path = prompt("Import sync file from (path on this machine):", "tollgate-sync.json");
      if (!path) return;
      const r = await api.post<{ logs_applied: number; config_events_applied: number }>(
        "/admin/sync/import",
        { path },
      );
      setMessage(`imported ${r.logs_applied} logs + ${r.config_events_applied} config events`);
      await load();
    } finally {
      setFileBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Sync</h1>
        <div className="flex gap-2">
          <Button disabled={fileBusy} onClick={exportFile}>
            <FileDown size={12} /> Export file
          </Button>
          <Button disabled={fileBusy} onClick={importFile}>
            <FileUp size={12} /> Import file
          </Button>
          <Button variant="primary" disabled={syncing} onClick={syncNow}>
            <RefreshCw size={12} className={syncing ? "animate-spin" : ""} /> Sync now
          </Button>
          <Button onClick={() => setAdding(true)}>
            <Plus size={12} /> Add peer
          </Button>
        </div>
      </div>

      {message && (
        <div className="rounded-md border border-[var(--color-line)] bg-zinc-900/50 px-3 py-2 text-[12px]">
          {message}
        </div>
      )}

      <Card
        title={
          <span className="inline-flex items-center gap-2">
            <TowerControl size={14} /> Peers
            {me && (
              <span className="text-[11px] text-[var(--color-muted)]">
                (this machine: {me.slice(0, 8)})
              </span>
            )}
          </span>
        }
      >
        {!state || state.peers.length === 0 ? (
          <Empty>
            No peers paired. On the other machine's Sync page, click "Add peer" with this
            machine's URL — it shows a pairing token once; paste that token here when
            adding the peer back. Stats then merge automatically every minute (and on
            "Sync now"); the machine scope selector filters to one machine or shows all.
          </Empty>
        ) : (
          <Table head={["Name", "URL", "Last seen", "Cursors (sent/received)", "Status", ""]}>
            {state.peers.map((p) => (
              <tr key={p.id} className="hover:bg-zinc-900/40">
                <td className="px-3 py-2 font-medium">{p.name}</td>
                <td className="px-3 py-2 font-mono text-[11px]">{p.endpoint_url}</td>
                <td className="px-3 py-2 text-[11px] text-[var(--color-muted)]">
                  {p.last_seen ? fmtTime(p.last_seen) : "never"}
                </td>
                <td className="px-3 py-2 font-mono text-[10px] text-[var(--color-muted)]">
                  {p.last_sent_cursor.slice(-6) || "–"} / {p.last_received_cursor.slice(-6) || "–"}
                </td>
                <td className="px-3 py-2">
                  {p.last_error ? (
                    <Badge tone="error">error</Badge>
                  ) : (
                    <Badge tone={p.enabled ? "active" : "disabled"}>
                      {p.enabled ? "ok" : "off"}
                    </Badge>
                  )}
                  {p.last_error && (
                    <div
                      className="mt-1 max-w-64 truncate text-[10px] text-red-400"
                      title={p.last_error}
                    >
                      {p.last_error}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Button
                    size="xs"
                    variant="danger"
                    onClick={async () => {
                      await api.del(`/admin/peers/${p.id}`);
                      load();
                    }}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Config audit log (last-writer-wins, newest wins)">
        {!state || state.audit.length === 0 ? (
          <Empty>No config changes recorded yet.</Empty>
        ) : (
          <Table head={["Time", "Entity", "Row", "Op", "Origin machine"]}>
            {state.audit.map((a) => (
              <tr key={a.id}>
                <td className="px-3 py-1.5 text-[11px] text-[var(--color-muted)]">
                  {fmtTime(a.ts)}
                </td>
                <td className="px-3 py-1.5">{a.entity}</td>
                <td className="px-3 py-1.5 font-mono text-[11px]">
                  {a.row_pk.length > 14 ? a.row_pk.slice(0, 14) + "…" : a.row_pk}
                </td>
                <td className="px-3 py-1.5">
                  <Badge tone={a.op === "tombstone" ? "error" : "info"}>{a.op}</Badge>
                </td>
                <td className="px-3 py-1.5 font-mono text-[11px] text-[var(--color-muted)]">
                  {a.origin_instance.slice(0, 8)}
                  {a.origin_instance === me && <span className="ml-1 text-indigo-400">(me)</span>}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {adding && (
        <AddPeerModal
          onClose={() => setAdding(false)}
          onSaved={() => {
            load(); // keep the modal open: it may still be showing the token
          }}
        />
      )}
    </div>
  );
}
