// Tiny shadcn-styled UI kit (dark, zinc + indigo accent).

import { type ReactNode } from "react";

export function Card({
  title,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] ${className}`}
    >
      {(title || right) && (
        <div className="flex items-center justify-between border-b border-[var(--color-line)] px-4 py-2.5">
          <div className="text-[13px] font-medium text-zinc-200">{title}</div>
          <div className="flex items-center gap-2">{right}</div>
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-panel)] px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-[var(--color-muted)]">{sub}</div>}
    </div>
  );
}

const badgeColors: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  disabled: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  blocked: "bg-red-500/15 text-red-400 border-red-500/30",
  expired: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  error: "bg-red-500/15 text-red-400 border-red-500/30",
  ok: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  info: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  warn: "bg-amber-500/15 text-amber-400 border-amber-500/30",
};

export function Badge({
  tone = "info",
  children,
}: {
  tone?: keyof typeof badgeColors | string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${
        badgeColors[tone] ?? badgeColors.info
      }`}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  size = "sm",
  disabled,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "danger" | "ghost";
  size?: "sm" | "xs";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const variants = {
    default:
      "border border-[var(--color-line)] bg-zinc-800/60 hover:bg-zinc-700/60 text-zinc-200",
    primary:
      "bg-[var(--color-accent)] hover:bg-indigo-500 text-white border border-transparent",
    danger:
      "border border-red-500/40 bg-red-500/10 hover:bg-red-500/20 text-red-400",
    ghost:
      "border border-transparent hover:bg-zinc-800/60 text-[var(--color-muted)]",
  };
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-40 ${
        size === "sm" ? "px-3 py-1.5 text-[12px]" : "px-2 py-1 text-[11px]"
      } ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-md border border-[var(--color-line)] bg-zinc-900/70 px-2.5 py-1.5 text-[12px] text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-indigo-500/60 ${props.className ?? ""}`}
    />
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`rounded-md border border-[var(--color-line)] bg-zinc-900/70 px-2 py-1.5 text-[12px] text-zinc-200 focus:outline-none focus:ring-1 focus:ring-indigo-500/60 ${props.className ?? ""}`}
    />
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </div>
      {children}
    </label>
  );
}

export function Table({
  head,
  children,
}: {
  head: ReactNode[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[12px]">
        <thead>
          <tr className="border-b border-[var(--color-line)] text-[11px] uppercase tracking-wide text-[var(--color-muted)]">
            {head.map((h, i) => (
              <th key={i} className="px-3 py-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-line)]">{children}</tbody>
      </table>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="py-10 text-center text-[12px] text-[var(--color-muted)]">
      {children}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-8"
      onClick={onClose}
    >
      <div
        className={`mt-8 w-full rounded-xl border border-[var(--color-line)] bg-[var(--color-panel)] shadow-2xl ${wide ? "max-w-3xl" : "max-w-md"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--color-line)] px-4 py-3">
          <div className="text-[13px] font-semibold">{title}</div>
          <button
            onClick={onClose}
            className="text-[var(--color-muted)] hover:text-zinc-200"
          >
            ✕
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
