import React from "react";

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "amber" | "emerald" | "violet" | "slate" }) {
  const map: Record<string, string> = {
    neutral: "bg-paper-muted text-ink-subtle ring-paper-border",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    violet: "bg-violet-50 text-violet-700 ring-violet-200",
    slate: "bg-slate-900 text-white ring-slate-900"
  };
  return <span className={["inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1", map[tone]].join(" ")}>{children}</span>;
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={["rounded-2xl border border-paper-border bg-white shadow-soft", className].join(" ")}>{children}</div>;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline"; size?: "sm" | "md" | "lg" }) {
  const variants: Record<string, string> = {
    primary: "bg-ink text-white hover:bg-action-hover shadow-sm",
    ghost: "bg-transparent text-ink hover:bg-paper-muted",
    outline: "border border-paper-border bg-white text-ink hover:bg-paper-muted"
  };
  const sizes: Record<string, string> = {
    sm: "px-3 py-1.5 text-xs",
    md: "px-4 py-2 text-sm",
    lg: "px-5 py-2.5 text-sm"
  };
  return (
    <button
      className={["inline-flex items-center justify-center rounded-full font-medium transition focus-visible:outline-none disabled:opacity-50", variants[variant], sizes[size]].join(" ")}
      {...props}
    >
      {children}
    </button>
  );
}

export function StatusDot({ status }: { status: "mock" | "connected" | "stale" | "error" | "pending_approval" }) {
  const map: Record<string, string> = {
    mock: "bg-amber-500",
    connected: "bg-emerald-500",
    stale: "bg-amber-500",
    error: "bg-red-500",
    pending_approval: "bg-violet-500"
  };
  return <span className={["inline-block h-2 w-2 rounded-full", map[status] ?? "bg-slate-400"].join(" ")} aria-hidden />;
}

export function ProvenanceDrawer({ open, onClose, title, provenance, children }: { open: boolean; onClose: () => void; title: string; provenance: any; children?: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal="true" aria-label={title}>
      <div className="flex-1 bg-ink/20 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div className="flex w-full max-w-[420px] flex-col bg-white shadow-elevated">
        <div className="border-b border-paper-border p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold tracking-widest text-ink-faint">PROVENIÊNCIA</div>
              <h2 className="mt-1 text-lg font-semibold tracking-tight text-ink">{title}</h2>
            </div>
            <button onClick={onClose} className="rounded-full bg-paper-muted p-2 text-ink-subtle hover:bg-paper-border" aria-label="Fechar">
              ✕
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-6">
          {provenance && (
            <div className="space-y-3">
              <div className="rounded-xl bg-paper-muted p-4">
                <div className="text-xs font-semibold tracking-widest text-ink-faint">ORIGEM</div>
                <div className="mt-1 text-sm font-medium text-ink">{provenance.origin}</div>
                {provenance.url && <div className="mt-1 break-all text-xs text-ink-subtle">{provenance.url}</div>}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-paper-border p-3">
                  <div className="text-xs text-ink-faint">Última verificação</div>
                  <div className="text-sm font-medium text-ink">{provenance.last_checked?.slice(0, 16).replace("T", " ")}</div>
                </div>
                <div className="rounded-xl border border-paper-border p-3">
                  <div className="text-xs text-ink-faint">Confiança</div>
                  <div className="text-sm font-medium capitalize text-ink">{provenance.confidence}</div>
                </div>
              </div>
              {provenance.note && <div className="rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 ring-1 ring-amber-200">{provenance.note}</div>}
              <div className="rounded-xl border border-dashed border-paper-border p-4">
                <div className="text-xs font-semibold text-ink-faint">ESCOPO E VALIDADE</div>
                <div className="mt-1 text-xs leading-relaxed text-ink-subtle">
                  Escopo: {provenance.scope ?? "pessoal"} · Validade: sincronização incremental · Distinção: observação (não inferência gerada por LLM).
                </div>
              </div>
            </div>
          )}
          {children}
        </div>
        <div className="border-t border-paper-border p-4">
          <div className="rounded-xl bg-ink px-4 py-3 text-xs leading-relaxed text-white/80">
            <span className="font-semibold text-white">DEMO</span> — dado fictício. Nenhuma fonte real foi consultada nesta tela.
          </div>
        </div>
      </div>
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-paper-border bg-paper-muted/50 px-6 py-10 text-center">
      <div className="mx-auto max-w-[420px]">
        <div className="text-sm font-semibold text-ink">{title}</div>
        <p className="mt-1 text-sm leading-relaxed text-ink-subtle">{description}</p>
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function StaleBanner({ reason }: { reason: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-amber-200">
      <span aria-hidden>⚠</span>
      <div>
        <div className="font-medium">Dados possivelmente desatualizados</div>
        <div className="text-xs leading-relaxed text-amber-700">{reason}</div>
      </div>
    </div>
  );
}
