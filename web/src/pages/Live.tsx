import LiveTail from "../LiveTail";

/** Full-page live tail: scrollable, newest first, this machine's gateway. */
export default function Live() {
  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Live</h1>
        <span className="text-[11px] text-[var(--color-muted)]">
          Requests and limit events from this machine's gateway, streamed live.
          Merged multi-machine history lives on Overview and Logs.
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <LiveTail maxEvents={400} listClassName="max-h-[calc(100vh-190px)]" />
      </div>
    </div>
  );
}
