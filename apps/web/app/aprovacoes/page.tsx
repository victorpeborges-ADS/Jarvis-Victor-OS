"use client";
import { useState } from "react";
import { fixtures, formatTimeH, DEMO_NOW } from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer } from "@/components/ui/primitives";

export default function AprovacoesPage() {
  const [states, setStates] = useState<Record<string, "pending" | "approved" | "rejected">>({ appr_001: "pending" });
  const [selectedAlt, setSelectedAlt] = useState<Record<string, string>>({ appr_001: "alt_a" });
  const [showTech, setShowTech] = useState<Record<string, boolean>>({});
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
        <Badge tone="violet">{approvals.filter((a) => (states[a.id] ?? "pending") === "pending").length} pendente(s)</Badge>
      </div>

      <div className="mt-4 rounded-xl border border-paper-border bg-paper-muted/60 px-4 py-3 text-xs leading-relaxed text-ink-subtle">
        <span className="font-medium text-ink">Rascunho local</span> = só nesta interface, sem tocar Calendar/Gmail.{" "}
        <span className="font-medium text-ink">Alteração externa</span> = escrita real (desativada até Gate 3).
      </div>

      <div className="mt-6 space-y-4">
        {approvals.map((appr) => {
          const s = states[appr.id] ?? "pending";
          const altId = selectedAlt[appr.id] ?? "alt_a";
          const alt = proposal.alternatives.find((a) => a.id === altId) ?? proposal.alternatives[0];
          const techOpen = showTech[appr.id] ?? false;

          return (
            <Card key={appr.id} className="overflow-hidden">
              <div className="p-5 md:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={[
                          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1",
                          s === "pending"
                            ? "bg-amber-50 text-amber-800 ring-amber-200"
                            : s === "approved"
                              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                              : "bg-paper-muted text-ink-subtle ring-paper-border"
                        ].join(" ")}
                      >
                        <span
                          className={[
                            "h-1.5 w-1.5 rounded-full",
                            s === "pending" ? "bg-amber-500" : s === "approved" ? "bg-emerald-500" : "bg-slate-400"
                          ].join(" ")}
                          aria-hidden
                        />
                        {s === "pending" ? "pendente de aprovação" : s === "approved" ? "aprovado (rascunho local)" : "rejeitado"}
                      </span>
                      <span className="text-xs text-ink-faint">Solicitado às {formatTimeH(appr.requested_at)}</span>
                    </div>
                    <h2 className="mt-2 text-[17px] font-semibold leading-tight text-ink">{appr.title}</h2>
                    <p className="mt-1 text-sm leading-relaxed text-ink-subtle">{appr.diff}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setDrawer(appr.id)}
                    className="shrink-0 rounded-full border border-paper-border bg-white px-3 py-1 text-xs font-medium text-ink hover:bg-paper-muted"
                  >
                    ver proveniência
                  </button>
                </div>

                <div className="mt-4 rounded-xl border border-paper-border bg-paper-muted p-4">
                  <div className="text-xs font-semibold tracking-widest text-ink-faint">DIFF EM LINGUAGEM NATURAL</div>
                  <div className="mt-1 text-sm leading-relaxed text-ink">
                    Antes: <span className="font-medium">18h00–19h00 Academia</span> → Depois (Alt A):{" "}
                    <span className="font-medium">17h00–17h30 Academia (leve)</span>
                  </div>
                  <div className="mt-2 text-xs leading-relaxed text-ink-subtle">{appr.scope}</div>
                </div>

                <fieldset className="mt-4">
                  <legend className="text-xs font-semibold tracking-widest text-ink-faint">ESCOLHA UMA ALTERNATIVA</legend>
                  <div className="mt-3 grid gap-3 md:grid-cols-2" role="radiogroup" aria-label="Alternativas da proposta">
                    {proposal.alternatives.map((option) => {
                      const selected = altId === option.id;
                      const letter = option.id === "alt_a" ? "A" : "B";
                      return (
                        <label
                          key={option.id}
                          className={[
                            "cursor-pointer rounded-xl border px-4 py-3 transition",
                            selected ? "border-ink bg-ink/[0.03] ring-2 ring-ink/20" : "border-paper-border bg-white hover:bg-paper-muted"
                          ].join(" ")}
                        >
                          <div className="flex items-start gap-3">
                            <input
                              type="radio"
                              name={`alt-${appr.id}`}
                              value={option.id}
                              checked={selected}
                              disabled={s !== "pending"}
                              onChange={() => setSelectedAlt({ ...selectedAlt, [appr.id]: option.id })}
                              className="mt-1"
                            />
                            <div>
                              <div className="text-xs font-semibold text-ink-faint">Alternativa {letter}</div>
                              <div className="mt-0.5 text-sm font-medium text-ink">{option.label}</div>
                              <div className="mt-1 text-xs leading-relaxed text-ink-subtle">{option.impact}</div>
                            </div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>

                <div className="mt-5 flex flex-wrap gap-2">
                  {s === "pending" ? (
                    <>
                      <Button
                        onClick={() => setStates({ ...states, [appr.id]: "approved" })}
                      >
                        Aprovar Alt {altId === "alt_a" ? "A" : "B"} — rascunho local
                      </Button>
                      <Button variant="outline" onClick={() => setStates({ ...states, [appr.id]: "rejected" })}>
                        Rejeitar
                      </Button>
                      <Button variant="ghost" type="button" disabled title="Revisão humana — sem efeito externo no Gate 1">
                        Pedir revisão
                      </Button>
                    </>
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={s === "approved" ? "emerald" : "neutral"}>
                        {s === "approved"
                          ? `Aprovado — rascunho local (Alt ${altId === "alt_a" ? "A" : "B"}); nenhuma escrita externa ainda (Gate 3 exigido)`
                          : "Rejeitado — nenhuma alteração foi feita"}
                      </Badge>
                      <Button variant="outline" size="sm" onClick={() => setStates({ ...states, [appr.id]: "pending" })}>
                        Reabrir
                      </Button>
                    </div>
                  )}
                </div>

                {s === "approved" && (
                  <p className="mt-3 text-xs leading-relaxed text-ink-subtle">
                    Escolhida: <span className="font-medium text-ink">{alt.label}</span>. Efeito: apenas registro local neste protótipo.
                  </p>
                )}

                <button
                  type="button"
                  className="mt-4 text-xs font-medium text-ink-faint underline decoration-ink/20 underline-offset-4 hover:decoration-ink"
                  onClick={() => setShowTech({ ...showTech, [appr.id]: !techOpen })}
                  aria-expanded={techOpen}
                >
                  {techOpen ? "Ocultar detalhes técnicos" : "Mostrar detalhes técnicos"}
                </button>
                {techOpen && (
                  <div className="mt-2 rounded-xl border border-dashed border-paper-border bg-paper-muted/50 px-3 py-3 text-xs leading-relaxed text-ink-subtle">
                    ID {appr.id} · chave idempotente <code className="rounded bg-white px-1 py-0.5 ring-1 ring-paper-border">{proposal.actions[0].idempotency_key}</code> ·
                    auditoria: você · {formatTimeH(DEMO_NOW)} (relógio DEMO) · motivo: conflito Academia×Entrega · resultado:{" "}
                    {s === "approved" ? "rascunho gerado" : "sem efeito"} — sem PII.
                  </div>
                )}
              </div>
              <div className="border-t border-paper-border bg-paper-muted px-5 py-3 text-xs leading-relaxed text-ink-subtle md:px-6">
                Gate 1: propostas são <span className="font-medium text-ink">só sugestões</span>. Escrita real só após testes de idempotência (Gate 3).
              </div>
            </Card>
          );
        })}
      </div>

      <Card className="mt-6 p-5">
        <h3 className="text-sm font-semibold text-ink">Como funciona a fila</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-relaxed text-ink-subtle">
          <li>JARVIS propõe com justificativa, fontes e CTA inequívoco.</li>
          <li>Você escolhe a alternativa, aprova ou rejeita — cada ação tem escopo e consequência.</li>
          <li>Ao aprovar no Gate 1, gera-se só rascunho local; alteração externa permanece bloqueada.</li>
        </ol>
      </Card>

      {approvals.map((appr) => (
        <ProvenanceDrawer
          key={appr.id}
          open={drawer === appr.id}
          onClose={() => setDrawer(null)}
          title={appr.title}
          provenance={{
            origin: "Regra determinística + fixtures",
            last_checked: "2026-09-23T08:50:00-03:00",
            confidence: "média",
            scope: "pessoal",
            note: "Chave idempotente evita duplicar ação mesmo com duplo clique."
          }}
        />
      ))}
    </div>
  );
}
