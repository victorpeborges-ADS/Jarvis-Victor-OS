"use client";
import { useState } from "react";
import { fixtures } from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer } from "@/components/ui/primitives";

export default function AprovacoesPage() {
  const [states, setStates] = useState<Record<string, "pending" | "approved" | "rejected">>({ appr_001: "pending" });
  const [drawer, setDrawer] = useState<string | null>(null);
  const approvals = fixtures.approvals;
  const proposal = fixtures.proposals[0];

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CENTRAL DE APROVAÇÃO</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Aprovações</h1>
          <p className="text-sm text-ink-subtle">Fila explícita. Toda alteração externa exige seu aceite.</p>
        </div>
        <Badge tone="violet">{approvals.length} pendente(s)</Badge>
      </div>

      <div className="mt-6 space-y-4">
        {approvals.map((appr: any) => {
          const s = states[appr.id] ?? "pending";
          return (
            <Card key={appr.id} className="overflow-hidden">
              <div className="p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className={["inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", s === "pending" ? "bg-amber-50 text-amber-800 ring-amber-200" : s === "approved" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-paper-muted text-ink-subtle ring-paper-border"].join(" ")}>
                        <span className={["h-1.5 w-1.5 rounded-full", s === "pending" ? "bg-amber-500" : s === "approved" ? "bg-emerald-500" : "bg-slate-400"].join(" ")} aria-hidden />
                        {s === "pending" ? "pendente de aprovação" : s === "approved" ? "aprovado (local)" : "rejeitado"}
                      </span>
                      <span className="text-xs text-ink-faint">ID {appr.id} · {appr.requested_at.slice(11, 16)}</span>
                    </div>
                    <h2 className="mt-2 text-[17px] font-semibold leading-tight text-ink">{appr.title}</h2>
                    <p className="mt-1 text-sm leading-relaxed text-ink-subtle">{appr.diff}</p>
                  </div>
                  <button onClick={() => setDrawer(appr.id)} className="shrink-0 rounded-full border border-paper-border bg-white px-3 py-1 text-xs font-medium text-ink hover:bg-paper-muted">
                    ver proveniência
                  </button>
                </div>

                <div className="mt-4 rounded-xl border border-paper-border bg-paper-muted p-4">
                  <div className="text-xs font-semibold tracking-widest text-ink-faint">DIFF EM LINGUAGEM NATURAL</div>
                  <div className="mt-1 text-sm leading-relaxed text-ink">
                    Antes: <span className="font-medium">18:00–19:00 Academia</span> → Depois: <span className="font-medium">17:00–17:30 Academia (leve)</span>
                  </div>
                  <div className="mt-2 text-xs leading-relaxed text-ink-subtle">
                    Escopo: {appr.scope} · Chave idempotente: <code className="rounded bg-white px-1 py-0.5 ring-1 ring-paper-border">{proposal.actions[0].idempotency_key}</code>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {proposal.alternatives.map((alt: any) => (
                    <div key={alt.id} className="rounded-xl border border-paper-border bg-white px-4 py-3">
                      <div className="text-sm font-medium text-ink">{alt.label}</div>
                      <div className="mt-1 text-xs leading-relaxed text-ink-subtle">{alt.impact}</div>
                      <div className="mt-2 text-xs font-medium text-ink-faint">Alternativa {alt.id === "alt_a" ? "A" : "B"}</div>
                    </div>
                  ))}
                </div>

                <div className="mt-5 flex flex-wrap gap-2">
                  {s === "pending" ? (
                    <>
                      <Button onClick={() => setStates({ ...states, [appr.id]: "approved" })}>Aprovar Alt A — rascunho local</Button>
                      <Button variant="outline" onClick={() => setStates({ ...states, [appr.id]: "rejected" })}>
                        Rejeitar
                      </Button>
                      <Button variant="ghost" onClick={() => setStates({ ...states, [appr.id]: "pending" })}>
                        Pedir revisão
                      </Button>
                    </>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Badge tone={s === "approved" ? "emerald" : "neutral"}>{s === "approved" ? "Aprovado — nenhuma escrita externa ainda (Gate 3 exigido)" : "Rejeitado — nenhuma alteração foi feita"}</Badge>
                      <Button variant="outline" size="sm" onClick={() => setStates({ ...states, [appr.id]: "pending" })}>
                        Reabrir
                      </Button>
                    </div>
                  )}
                </div>

                <p className="mt-3 text-xs leading-relaxed text-ink-faint">
                  Auditoria: quem (você), quando ({new Date().toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}), o que ({appr.title}), por que (conflito Academia×Entrega), aprovação {s}, resultado: {s === "approved" ? "rascunho gerado" : "sem efeito"} — sem PII nos logs.
                </p>
              </div>
              <div className="border-t border-paper-border bg-paper-muted px-6 py-3 text-xs leading-relaxed text-ink-subtle">
                Gate 1: propostas são <span className="font-medium text-ink">só sugestões</span>. Escrita real só após testes de idempotência, concorrência e revogação (Gate 3).
              </div>
            </Card>
          );
        })}
      </div>

      <Card className="mt-6 p-5">
        <h3 className="text-sm font-semibold text-ink">Como funciona a fila</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-relaxed text-ink-subtle">
          <li>JARVIS propõe com justificativa, fontes e CTA inequívoco.</li>
          <li>Você aprova ou rejeita — cada ação tem escopo, alvo e consequência explícitos.</li>
          <li>Ao aprovar, executa só a ação autorizada e registra evidência; ao rejeitar, respeita.</li>
        </ol>
      </Card>

      {approvals.map((appr: any) => (
        <ProvenanceDrawer key={appr.id} open={drawer === appr.id} onClose={() => setDrawer(null)} title={appr.title} provenance={{ origin: "Regra determinística + fixtures", last_checked: "2026-09-23T08:50:00-03:00", confidence: "média", scope: "pessoal", note: "Idempotency key garante não duplicar ação mesmo com duplo clique." }} />
      ))}
    </div>
  );
}
