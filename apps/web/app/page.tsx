"use client";
import { useState } from "react";
import Link from "next/link";
import { fixtures, getEvent, formatTime, formatDate } from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer, StatusDot, StaleBanner } from "@/components/ui/primitives";

export default function AgoraPage() {
  const [drawer, setDrawer] = useState<string | null>(null);
  const [approvalState, setApprovalState] = useState<"pending" | "approved" | "rejected">("pending");

  const nextEvent = getEvent(fixtures.briefing.next_commitment);
  const briefing = fixtures.briefing;
  const conflict = fixtures.proposals[0];
  const driveStale = fixtures.sources.find((s) => s.sync_status === "stale");

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8 md:py-8">
      {/* Top meta */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">AGORA · {formatDate(briefing.date + "T09:00:00-03:00")}</div>
          <h1 className="prose-editorial mt-1 text-[28px] font-[500] leading-none tracking-tight text-ink md:text-[34px]">Bom dia, Victor.</h1>
          <p className="mt-1 max-w-[560px] text-sm leading-relaxed text-ink-subtle">
            Em até 5 segundos: próximo compromisso, uma prioridade, um alerta com consequência.
          </p>
        </div>
        <Badge tone="amber">DEMO · {fixtures.meta.timezone}</Badge>
      </div>

      {/* 5s hero — Próximo compromisso */}
      <Card className="mt-6 overflow-hidden">
        <div className="flex flex-col md:flex-row">
          <div className="flex-1 p-6 md:p-7">
            <div className="flex items-center gap-2 text-xs font-semibold tracking-widest text-ink-faint">
              <StatusDot status="connected" /> PRÓXIMO COMPROMISSO · EM 25 MIN
            </div>
            <h2 className="prose-editorial mt-2 text-[22px] font-medium leading-tight text-ink md:text-[26px]">{nextEvent?.title}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-subtle">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-paper-muted px-2.5 py-1 text-xs font-medium text-ink">
                <span aria-hidden>◷</span> {nextEvent && formatTime(nextEvent.occurred_at)} · {nextEvent?.payload_minimized?.location}
              </span>
              <span className="text-xs">America/Sao_Paulo</span>
            </div>
            <p className="mt-3 max-w-[520px] text-sm leading-relaxed text-ink-muted">
              Revisão rápida da sprint. Leve os slides da demo — a entrega às 19h depende deles.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button onClick={() => setDrawer("next")}>Ver por que isso importa</Button>
              <Link href="/aprovacoes" className="inline-flex items-center justify-center rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted">
                Ver linha do tempo
              </Link>
            </div>
          </div>
          <div className="border-t border-paper-border bg-paper-muted p-4 md:w-[260px] md:border-l md:border-t-0">
            <div className="text-xs font-semibold tracking-widest text-ink-faint">EVIDÊNCIA</div>
            <div className="mt-2 text-xs leading-relaxed text-ink-subtle">
              Origem <span className="font-medium text-ink">{nextEvent?.provenance.origin}</span> · verificado às {nextEvent?.provenance.last_checked.slice(11, 16)} · confiança alta
            </div>
            <div className="mt-3 rounded-xl bg-white p-3 ring-1 ring-paper-border">
              <div className="text-xs font-medium text-ink">Observação — não inferência</div>
              <div className="mt-1 text-xs leading-relaxed text-ink-subtle">Este horário vem da fonte. Não assumimos presença sem confirmação.</div>
            </div>
          </div>
        </div>
      </Card>

      {/* Prioridade + Alerta — 1–3 decisões úteis */}
      <div className="mt-4 grid gap-4 md:grid-cols-[1.15fr_0.85fr]">
        <Card className="p-6">
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold tracking-widest text-ink-faint">PRIORIDADE ESSENCIAL · 1 DE 3</div>
            <Badge tone="violet">Recomendação</Badge>
          </div>
          <h3 className="mt-2 text-[18px] font-semibold leading-tight text-ink">{briefing.priority.title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">{briefing.priority.rationale}</p>
          <div className="mt-3 rounded-xl bg-paper-muted p-3">
            <div className="text-xs font-medium text-ink">Por quê agora?</div>
            <div className="mt-1 text-xs leading-relaxed text-ink-subtle">
              Evidência: <Link href="/fontes" className="underline decoration-ink/20 underline-offset-4 hover:decoration-ink">Entrega 19h</Link> · confiança alta · última verificação 08:45
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <Button size="sm" onClick={() => setDrawer("priority")}>
              Ver fontes
            </Button>
            <Link href="/conversa" className="inline-flex items-center rounded-full bg-paper-muted px-3 py-1.5 text-xs font-medium text-ink hover:bg-paper-border">
              Perguntar ao JARVIS
            </Link>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-2 text-xs font-semibold tracking-widest text-amber-700">
            <span aria-hidden>⚠</span> ALERTA COM CONSEQUÊNCIA
          </div>
          <h3 className="mt-2 text-[16px] font-semibold leading-tight text-ink">{briefing.alerts[0].title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-subtle">
            {briefing.alerts[0].consequence}. Duas alternativas prontas — sem execução automática.
          </p>
          <div className="mt-3 rounded-xl bg-amber-50 p-3 ring-1 ring-amber-200">
            <div className="text-xs font-medium text-amber-800">Distinção clara</div>
            <div className="mt-1 text-xs leading-relaxed text-amber-700">Proposta ≠ alteração realizada. Toda mudança exige sua aprovação explícita.</div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href="/aprovacoes" className="inline-flex items-center justify-center rounded-full bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-action-hover">
              Resolver conflito →
            </Link>
            <Button variant="ghost" size="sm" onClick={() => setDrawer("alert")}>
              Ver evidência
            </Button>
          </div>
        </Card>
      </div>

      {/* Energia opcional */}
      <div className="mt-4 rounded-2xl border border-paper-border bg-white px-5 py-4 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full bg-paper-muted text-xs" aria-hidden>
            ◐
          </span>
          <div>
            <div className="text-xs font-semibold tracking-widest text-ink-faint">ENERGIA / CAPACIDADE — OPCIONAL</div>
            <p className="mt-1 text-sm leading-relaxed text-ink-subtle">{briefing.energy_optional.suggestion}</p>
          </div>
        </div>
      </div>

      {/* Timeline compacta */}
      <Card className="mt-4 p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold tracking-tight text-ink">Linha do tempo — hoje</h3>
          <Link href="/fontes" className="text-xs font-medium text-ink-subtle underline decoration-ink/20 underline-offset-4 hover:decoration-ink">
            Ver todas as fontes
          </Link>
        </div>
        <div className="relative mt-4">
          <div className="absolute bottom-0 left-[11px] top-0 w-px bg-paper-border" aria-hidden />
          <ul className="space-y-3" role="list">
            {fixtures.events.slice(0, 4).map((ev) => (
              <li key={ev.id} className="relative flex gap-3">
                <span className="relative z-10 mt-1 flex h-[22px] w-[22px] items-center justify-center rounded-full border border-paper-border bg-white text-[10px]">●</span>
                <div className="min-w-0 flex-1 rounded-xl border border-paper-border bg-paper-muted px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-sm font-medium leading-tight text-ink">{ev.title}</div>
                    <span className="shrink-0 text-xs text-ink-faint">{formatTime(ev.occurred_at)}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs text-ink-subtle">{ev.provenance.origin}</span>
                    <span className="text-xs text-ink-faint">·</span>
                    <button onClick={() => setDrawer(ev.id)} className="text-xs font-medium text-ink underline decoration-ink/20 underline-offset-4 hover:decoration-ink">
                      evidência
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="mt-4 flex items-center justify-between rounded-xl bg-paper-muted px-3 py-2 text-xs text-ink-subtle">
          <span>Fuso horário: America/Sao_Paulo · 3 eventos hoje</span>
          <span className="hidden md:inline">Mock · conectado 08:47</span>
        </div>
      </Card>

      {/* Stale + captura rápida */}
      {driveStale && (
        <div className="mt-4">
          <StaleBanner reason={driveStale.stale_reason ?? "Sem sincronização recente"} />
        </div>
      )}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CAPTURA RÁPIDA — JORNADA 3</div>
          <h3 className="mt-1 text-sm font-semibold text-ink">Ideia capturada e vinculada sem criar reunião</h3>
          <p className="mt-1 text-sm leading-relaxed text-ink-subtle">“{fixtures.inbox[0].title}” — classificada como referência, projeto CRIVO.</p>
          <div className="mt-3 flex gap-2">
            <Link href="/inbox" className="inline-flex items-center rounded-full bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-action-hover">
              Abrir Inbox
            </Link>
            <Link href="/dominios" className="inline-flex items-center rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted">
              Ver Domínios
            </Link>
          </div>
        </Card>

        <Card className="p-5">
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CONFLITO — JORNADA 2</div>
          <h3 className="mt-1 text-sm font-semibold text-ink">2 alternativas respeitando sua rotina</h3>
          <div className="mt-2 space-y-2">
            {conflict.alternatives.map((alt: any) => (
              <div key={alt.id} className="rounded-xl border border-paper-border bg-paper-muted px-3 py-2">
                <div className="text-xs font-medium text-ink">{alt.label}</div>
                <div className="text-xs leading-relaxed text-ink-subtle">{alt.impact}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2">
            {approvalState === "pending" ? (
              <>
                <Button size="sm" onClick={() => setApprovalState("approved")}>
                  Aprovar Alt A (mock)
                </Button>
                <Button variant="outline" size="sm" onClick={() => setApprovalState("rejected")}>
                  Rejeitar
                </Button>
              </>
            ) : (
              <Badge tone={approvalState === "approved" ? "emerald" : "neutral"}>
                {approvalState === "approved" ? "Aprovado (local, sem escrita externa)" : "Rejeitado — nenhuma alteração feita"}
              </Badge>
            )}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-faint">Nenhum evento externo foi alterado. Ação é rascunho com chave idempotente {conflict.actions[0].idempotency_key}.</p>
        </Card>
      </div>

      <div className="mt-8 rounded-2xl border border-dashed border-paper-border bg-paper-muted/40 px-4 py-3 text-center text-xs leading-relaxed text-ink-subtle">
        Todas as informações exibidas são <span className="font-medium text-ink">DEMO fictícias</span> · <Link href="/fontes" className="underline">proveniência visível por item</Link> · sem OAuth real neste Gate.
      </div>

      {/* Drawers */}
      <ProvenanceDrawer open={drawer === "next"} onClose={() => setDrawer(null)} title={nextEvent?.title ?? ""} provenance={nextEvent?.provenance} />
      <ProvenanceDrawer open={drawer === "priority"} onClose={() => setDrawer(null)} title={briefing.priority.title} provenance={{ origin: "Regra determinística + fixtures", last_checked: "2026-09-23T08:45:00-03:00", confidence: "alta", scope: "MedSyn" }} />
      <ProvenanceDrawer open={drawer === "alert"} onClose={() => setDrawer(null)} title={briefing.alerts[0].title} provenance={getEvent(briefing.alerts[0].evidence_event_ids[0])?.provenance} />
      {fixtures.events.map((ev) => (
        <ProvenanceDrawer key={ev.id} open={drawer === ev.id} onClose={() => setDrawer(null)} title={ev.title} provenance={ev.provenance} />
      ))}
    </div>
  );
}
