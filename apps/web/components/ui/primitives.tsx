"use client";

import React from "react";
import { Dialog } from "@/components/ui/Dialog";

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "amber" | "emerald" | "violet" | "slate" | "red" }) {
  const map: Record<string, string> = {
    neutral: "bg-paper-muted text-ink-subtle ring-paper-border",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    violet: "bg-violet-50 text-violet-700 ring-violet-200",
    slate: "bg-slate-900 text-white ring-slate-900",
    red: "bg-red-50 text-red-800 ring-red-200"
  };
  return <span className={["inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1", map[tone]].join(" ")}>{children}</span>;
}

export function Card({ children, className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={["rounded-2xl border border-paper-border bg-white shadow-soft", className].join(" ")}>{children}</div>;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline"; size?: "sm" | "md" | "lg" }) {
  const variants: Record<string, string> = {
    primary: "bg-ink text-white hover:bg-action-hover shadow-sm",
    ghost: "bg-transparent text-ink hover:bg-paper-muted",
    outline: "border border-paper-border bg-white text-ink hover:bg-paper-muted"
  };
  const sizes: Record<string, string> = {
    sm: "min-h-11 min-w-11 px-3 py-1.5 text-xs",
    md: "min-h-11 min-w-11 px-4 py-2 text-sm",
    lg: "min-h-11 min-w-11 px-5 py-2.5 text-sm"
  };
  return (
    <button
      className={["inline-flex items-center justify-center rounded-full font-medium transition disabled:opacity-60", variants[variant], sizes[size], className].join(" ")}
      {...props}
    >
      {children}
    </button>
  );
}

export function StatusDot({ status }: { status: "mock" | "connected" | "stale" | "error" | "pending_approval" }) {
  // O estado de exemplo usa cinza e não sugere uma conexão real.
  const map: Record<string, string> = {
    mock: "bg-slate-500",
    connected: "bg-emerald-600",
    stale: "bg-amber-600",
    error: "bg-red-500",
    pending_approval: "bg-violet-500"
  };
  return <span className={["inline-block h-2 w-2 rounded-full", map[status] ?? "bg-slate-400"].join(" ")} aria-hidden />;
}

/** A demonstração fica neutra; alertas de desatualização usam âmbar e símbolo. */
export function ConnectorBadge({ status, label }: { status: string; label: string }) {
  const stale = status === "stale";
  const dotStatus: "mock" | "stale" | "error" | "pending_approval" =
    status === "stale" ? "stale" : status === "error" ? "error" : status === "pending_approval" ? "pending_approval" : "mock";
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium ring-1",
        stale ? "bg-amber-50 text-amber-900 ring-amber-300" : "bg-slate-100 text-slate-800 ring-slate-300"
      ].join(" ")}
      title={stale ? "Dados de demonstração possivelmente desatualizados" : "Dados de demonstração; nenhuma conta está conectada"}
    >
      {stale && <span aria-hidden>⚠</span>}
      <StatusDot status={dotStatus} />
      {label}
    </span>
  );
}

export function ProvenanceDrawer({ open, onClose, title, provenance, children }: { open: boolean; onClose: () => void; title: string; provenance: any; children?: React.ReactNode }) {
  const titleId = "origem-informacao-titulo";
  const timestamp = (value?: string | null) => value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })
    : "Não informado nesta demonstração";
  return (
    <Dialog open={open} onClose={onClose} titleId={titleId} label={title || "Origem das informações"}>
      <div className="border-b border-paper-border p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold tracking-widest text-ink-faint">ORIGEM DAS INFORMAÇÕES</div>
            <h2 id={titleId} className="mt-1 text-lg font-semibold tracking-tight text-ink">{title}</h2>
          </div>
          <button type="button" onClick={onClose} className="min-h-11 min-w-11 rounded-full bg-paper-muted p-2 text-ink-subtle hover:bg-paper-border" aria-label="Fechar" data-testid="drawer-close">
            <span aria-hidden>✕</span>
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-6">
          {provenance && (
            <div className="space-y-3">
              <div className="rounded-xl bg-paper-muted p-4">
              <div className="text-xs font-semibold tracking-widest text-ink-faint">DE ONDE VEIO</div>
              <div className="mt-1 text-sm font-medium text-ink">{provenance.origin}</div>
              {provenance.url && <div className="mt-1 break-all text-xs text-ink-subtle">{provenance.url}</div>}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Identificador da informação</div><div className="break-all text-sm font-medium text-ink">{provenance.id ?? "Não informado nesta demonstração"}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Identificador da fonte</div><div className="break-all text-sm font-medium text-ink">{provenance.source_id ?? "Não informado nesta demonstração"}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Referência na origem</div><div className="break-all text-sm font-medium text-ink">{provenance.external_ref ?? "Não informada nesta demonstração"}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Observada em</div><div className="text-sm font-medium text-ink">{timestamp(provenance.observed_at)}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Última verificação</div><div className="text-sm font-medium text-ink">{timestamp(provenance.last_checked ?? provenance.last_verified_at)}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Validade</div><div className="text-sm font-medium text-ink">{provenance.valid_until ? timestamp(provenance.valid_until) : "Sem prazo informado"}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Confiança da informação</div><div className="text-sm font-medium capitalize text-ink">{provenance.confidence ?? "Não informada"}</div></div>
              <div className="rounded-xl border border-paper-border p-3"><div className="text-xs text-ink-faint">Área de aplicação</div><div className="text-sm font-medium capitalize text-ink">{provenance.scope ?? "Não informada"}</div></div>
            </div>
            {provenance.note && <div className="rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 ring-1 ring-amber-200">{provenance.note}</div>}
            <div className="rounded-xl border border-dashed border-paper-border p-4">
              <div className="text-xs font-semibold text-ink-faint">ONDE SE APLICA</div>
              <div className="mt-1 text-xs leading-relaxed text-ink-subtle">
                {provenance.scope ?? "Área não informada"}. Informação observada nas fontes apresentadas; a demonstração não cria fatos por conta própria.
              </div>
            </div>
            <details className="rounded-xl border border-paper-border px-4 py-3 text-xs text-ink-subtle">
              <summary className="min-h-11 cursor-pointer py-3 font-medium text-ink">Detalhes técnicos da origem</summary>
              <p className="mt-2">Registro de origem, horário da última conferência, nível de confiança e domínio de acesso.</p>
            </details>
          </div>
        )}
        {children}
      </div>
      <div className="border-t border-paper-border p-4">
        <div className="rounded-xl bg-ink px-4 py-3 text-sm leading-relaxed text-white">
          <span className="font-semibold">Demonstração</span> — dados de exemplo. Nenhuma conta pessoal ou institucional foi consultada.
        </div>
      </div>
    </Dialog>
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
