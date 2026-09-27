"use client";
import { useState } from "react";
import { fixtures, formatTimeH, DEMO_NOW } from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer } from "@/components/ui/primitives";

export default function AprovacoesPage() {
  const [states, setStates] = useState<Record<string, "pending" | "approved" | "rejected">>({ appr_001: "pending" });
  const [selectedAlt, setSelectedAlt] = useState<Record<string, string>>({ appr_001: "alt_a" });
  const [showTech, setShowTech] = useState<Record<string, boolean>>({});
  const [drawer, setDrawer] = useState<string | null>(null);
  const [reviewRequested, setReviewRequested] = useState<Record<string, boolean>>({});
  const approvals = fixtures.approvals;
  const proposal = fixtures.proposals[0];
  const pendingCount = approvals.filter((a) => (states[a.id] ?? "pending") === "pending").length;

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">DECISÕES</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Aprovações</h1>
          <p className="text-sm text-ink-subtle">Revise as sugestões antes de escolher uma opção.</p>
        </div>
        <span className="whitespace-nowrap"><Badge tone="violet">{pendingCount} {pendingCount === 1 ? "pendente" : "pendentes"}</Badge></span>
      </div>

      <div className="mt-4 rounded-xl border border-paper-border bg-paper-muted/60 px-4 py-3 text-xs leading-relaxed text-ink-subtle">
        As escolhas nesta página são demonstrações locais. Nenhuma conta ou agenda é alterada.
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
                    className="inline-flex min-h-11 shrink-0 items-center rounded-full border border-paper-border bg-white px-3 py-2 text-xs font-medium text-ink hover:bg-paper-muted"
                  >
                    De onde veio esta informação
                  </button>
                </div>

                <div className="mt-4 rounded-xl border border-paper-border bg-paper-muted p-4">
                  <div className="text-xs font-semibold tracking-widest text-ink-faint">RESUMO DA MUDANÇA</div>
                  <div className="mt-1 text-sm leading-relaxed text-ink">
                    Antes: <span className="font-medium">18h00–19h00 Academia</span> → Depois (opção A):{" "}
                    <span className="font-medium">17h00–17h30 Academia (leve)</span>
                  </div>
                  <div className="mt-2 text-xs leading-relaxed text-ink-subtle">Esta é uma sugestão. Nenhuma agenda ou conta é alterada.</div>
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
                              <div className={["mt-1 text-xs leading-relaxed", selected ? "text-ink-onSelected" : "text-ink-subtle"].join(" ")}>
                                {option.impact}
                              </div>
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
                        Aprovar sugestão {altId === "alt_a" ? "A" : "B"} — somente nesta tela
                      </Button>
                      <Button variant="outline" onClick={() => setStates({ ...states, [appr.id]: "rejected" })}>
                        Rejeitar
                      </Button>
                      <Button variant="ghost" type="button" onClick={() => setReviewRequested({ ...reviewRequested, [appr.id]: true })} aria-describedby={`review-help-${appr.id}`}>
                        Solicitar revisão
                      </Button>
                    </>
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={s === "approved" ? "emerald" : "neutral"}>
                        {s === "approved"
                          ? `Sugestão aprovada nesta demonstração (opção ${altId === "alt_a" ? "A" : "B"}); nenhuma conta foi alterada.`
                          : "Rejeitado — nenhuma alteração foi feita"}
                      </Badge>
                      <Button variant="outline" size="sm" onClick={() => setStates({ ...states, [appr.id]: "pending" })}>
                        Reabrir
                      </Button>
                    </div>
                  )}
                </div>

                {s === "pending" && (
                  <p id={`review-help-${appr.id}`} className="mt-2 min-h-6 text-xs text-ink-subtle" role="status" aria-live="polite">
                    {reviewRequested[appr.id] ? "Pedido de revisão registrado nesta demonstração." : "Solicitar revisão registra apenas um pedido nesta demonstração."}
                  </p>
                )}

                {s === "approved" && (
                  <p className="mt-3 text-xs leading-relaxed text-ink-subtle">
                    Escolhida: <span className="font-medium text-ink">{alt.label}</span>. Efeito: apenas registro local neste protótipo.
                  </p>
                )}

                <button
                  type="button"
                  className="mt-4 inline-flex min-h-11 items-center text-xs font-medium text-ink-faint underline decoration-ink/20 underline-offset-4 hover:decoration-ink"
                  onClick={() => setShowTech({ ...showTech, [appr.id]: !techOpen })}
                  aria-expanded={techOpen}
                >
                  {techOpen ? "Ocultar detalhes técnicos" : "Mostrar detalhes técnicos"}
                </button>
                {techOpen && (
                  <div className="mt-2 rounded-xl border border-dashed border-paper-border bg-paper-muted/50 px-3 py-3 text-xs leading-relaxed text-ink-subtle">
                    ID {appr.id} · chave idempotente <code className="rounded bg-white px-1 py-0.5 ring-1 ring-paper-border">{proposal.actions[0].idempotency_key}</code> ·
                    registro: você · {formatTimeH(DEMO_NOW)} (horário de referência) · motivo: conflito Academia×Entrega · resultado:{" "}
                    {s === "approved" ? "rascunho gerado" : "sem efeito"} — sem PII.
                  </div>
                )}
              </div>
              <div className="border-t border-paper-border bg-paper-muted px-5 py-3 text-xs leading-relaxed text-ink-subtle md:px-6">
                Esta é uma sugestão de exemplo. A aprovação nesta página não altera serviços ou contas.
              </div>
            </Card>
          );
        })}
      </div>

      <Card className="mt-6 p-5">
        <h3 className="text-sm font-semibold text-ink">Como funciona a fila</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-relaxed text-ink-subtle">
          <li>JARVIS apresenta a justificativa, as fontes e uma ação clara.</li>
          <li>Você escolhe a alternativa, aprova ou rejeita — cada ação tem escopo e consequência.</li>
          <li>A decisão registrada aqui vale apenas para esta demonstração.</li>
        </ol>
      </Card>

      {approvals.map((appr) => (
        <ProvenanceDrawer
          key={appr.id}
          open={drawer === appr.id}
          onClose={() => setDrawer(null)}
          title={appr.title}
          provenance={{
            origin: "Informações de exemplo",
            id: proposal.id,
            source_id: proposal.conflicts.join(", "),
            external_ref: proposal.actions[0]?.id,
            observed_at: appr.requested_at,
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
