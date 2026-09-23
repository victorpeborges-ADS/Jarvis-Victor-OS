"use client";
import { useState } from "react";
import Link from "next/link";
import {
  fixtures,
  getEvent,
  formatTimeH,
  formatDate,
  greetingFromHour,
  formatMinutesUntil,
  commitmentsToday,
  messagesToday,
  DEMO_NOW
} from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer, StatusDot, StaleBanner } from "@/components/ui/primitives";

export default function AgoraPage() {
  const [drawer, setDrawer] = useState<string | null>(null);

  const nextEvent = getEvent(fixtures.briefing.next_commitment);
  const briefing = fixtures.briefing;
  const driveStale = fixtures.sources.find((s) => s.sync_status === "stale");
  const commitments = commitmentsToday();
  const messages = messagesToday();
  const relative = nextEvent ? formatMinutesUntil(nextEvent.occurred_at) : "";
  const greeting = greetingFromHour(DEMO_NOW);

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">
            AGORA · {formatDate(briefing.date + "T09:00:00-03:00")}
          </div>
          <h1 className="prose-editorial mt-1 text-[28px] font-[500] leading-none tracking-tight text-ink md:text-[34px]">
            {greeting}, Victor.
          </h1>
          <p className="mt-1 max-w-[560px] text-sm leading-relaxed text-ink-subtle">
            Em até 5 segundos: próximo compromisso, uma prioridade, um alerta.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Badge tone="amber">DEMO · {fixtures.meta.timezone}</Badge>
          <span className="text-[11px] text-ink-faint" title="Relógio fixo das fixtures">
            Relógio DEMO {formatTimeH(DEMO_NOW)}
          </span>
        </div>
      </div>

      {/* Hero — próximo compromisso (5s) */}
      <Card className="mt-6 p-5 md:p-6">
        <div className="flex items-center gap-2 text-xs font-semibold tracking-widest text-ink-faint">
          <StatusDot status="mock" /> PRÓXIMO COMPROMISSO · {relative.toUpperCase()}
        </div>
        <h2 className="prose-editorial mt-2 text-[22px] font-medium leading-tight text-ink md:text-[26px]">
          {nextEvent?.title}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-subtle">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-paper-muted px-2.5 py-1 text-xs font-medium text-ink">
            <span aria-hidden>◷</span> {nextEvent && formatTimeH(nextEvent.occurred_at)} · {nextEvent?.payload_minimized?.location}
          </span>
        </div>
        <p className="mt-3 max-w-[520px] text-sm leading-relaxed text-ink-muted">
          Revisão rápida da sprint. Leve os slides — a entrega às 19h depende deles.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => setDrawer("next")}>Por que isso importa</Button>
          <a
            href="#linha-do-tempo"
            className="inline-flex items-center justify-center rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted"
          >
            Ver linha do tempo
          </a>
        </div>
      </Card>

      {/* Prioridade + Alerta */}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5 md:p-6">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-semibold tracking-widest text-ink-faint">PRIORIDADE ESSENCIAL</div>
            <Badge tone="violet">1 de 3</Badge>
          </div>
          <h3 className="mt-2 text-[17px] font-semibold leading-tight text-ink">{briefing.priority.title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">{briefing.priority.rationale}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setDrawer("priority")}>
              Ver evidência
            </Button>
            <Link
              href="/conversa"
              className="inline-flex items-center rounded-full bg-paper-muted px-3 py-1.5 text-xs font-medium text-ink hover:bg-paper-border"
            >
              Perguntar ao JARVIS
            </Link>
          </div>
        </Card>

        <Card className="p-5 md:p-6">
          <div className="flex items-center gap-2 text-xs font-semibold tracking-widest text-amber-700">
            <span aria-hidden>⚠</span> ALERTA COM CONSEQUÊNCIA
          </div>
          <h3 className="mt-2 text-[16px] font-semibold leading-tight text-ink">{briefing.alerts[0].title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-subtle">
            {briefing.alerts[0].consequence}. Duas alternativas prontas — sem execução automática.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href="/aprovacoes"
              className="inline-flex items-center justify-center rounded-full bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-action-hover"
            >
              Resolver conflito →
            </Link>
            <Button variant="ghost" size="sm" onClick={() => setDrawer("alert")}>
              Ver evidência
            </Button>
          </div>
        </Card>
      </div>

      {/* Energia compacta */}
      <p className="mt-4 px-1 text-sm leading-relaxed text-ink-subtle">
        <span className="font-medium text-ink">Energia:</span> {briefing.energy_optional.suggestion}
      </p>

      {/* Timeline — compromissos separados de mensagens */}
      <Card className="mt-4 p-5 md:p-6" id="linha-do-tempo">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold tracking-tight text-ink">Linha do tempo — hoje</h3>
          <Link href="/fontes" className="text-xs font-medium text-ink-subtle underline decoration-ink/20 underline-offset-4 hover:decoration-ink">
            Fontes
          </Link>
        </div>

        <div className="mt-4">
          <div className="text-xs font-semibold tracking-widest text-ink-faint">
            COMPROMISSOS · {commitments.length}
          </div>
          <ul className="relative mt-3 space-y-3" role="list">
            <div className="absolute bottom-0 left-[11px] top-0 w-px bg-paper-border" aria-hidden />
            {commitments.map((ev) => (
              <li key={ev.id} className="relative flex gap-3">
                <span className="relative z-10 mt-1 flex h-[22px] w-[22px] items-center justify-center rounded-full border border-paper-border bg-white text-[10px]">
                  ●
                </span>
                <div className="min-w-0 flex-1 rounded-xl border border-paper-border bg-paper-muted px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-sm font-medium leading-tight text-ink">{ev.title}</div>
                    <span className="shrink-0 text-xs text-ink-faint">{formatTimeH(ev.occurred_at)}</span>
                  </div>
                  <button
                    onClick={() => setDrawer(ev.id)}
                    className="mt-1 text-xs font-medium text-ink underline decoration-ink/20 underline-offset-4 hover:decoration-ink"
                  >
                    evidência · {ev.provenance.origin}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-5 border-t border-paper-border pt-4">
          <div className="text-xs font-semibold tracking-widest text-ink-faint">
            MENSAGENS · {messages.length}
          </div>
          <ul className="mt-3 space-y-2" role="list">
            {messages.map((ev) => (
              <li key={ev.id} className="flex items-start justify-between gap-3 rounded-xl border border-dashed border-paper-border bg-white px-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-sm font-medium leading-tight text-ink">{ev.title}</div>
                  <button
                    onClick={() => setDrawer(ev.id)}
                    className="mt-1 text-xs font-medium text-ink-subtle underline decoration-ink/20 underline-offset-4"
                  >
                    {ev.provenance.origin}
                  </button>
                </div>
                <span className="shrink-0 text-xs text-ink-faint">{formatTimeH(ev.occurred_at)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-4 rounded-xl bg-paper-muted px-3 py-2 text-xs text-ink-subtle">
          Fuso America/Sao_Paulo · {commitments.length} compromissos · {messages.length} mensagens · mock {formatTimeH(DEMO_NOW)}
        </div>
      </Card>

      {driveStale && (
        <div className="mt-4">
          <StaleBanner reason="Drive (simulado) sem sincronização há 24h — só esta fonte está marcada como desatualizada." />
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Link href="/inbox" className="inline-flex items-center rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted">
          Inbox · captura CRIVO
        </Link>
        <Link href="/aprovacoes" className="inline-flex items-center rounded-full border border-paper-border bg-white px-4 py-2 text-sm font-medium text-ink hover:bg-paper-muted">
          Aprovações · 2 alternativas
        </Link>
      </div>

      <div className="mt-8 rounded-2xl border border-dashed border-paper-border bg-paper-muted/40 px-4 py-3 text-center text-xs leading-relaxed text-ink-subtle">
        Informações <span className="font-medium text-ink">DEMO fictícias</span> ·{" "}
        <Link href="/fontes" className="underline">
          proveniência por item
        </Link>{" "}
        · sem OAuth real neste Gate.
      </div>

      <ProvenanceDrawer open={drawer === "next"} onClose={() => setDrawer(null)} title={nextEvent?.title ?? ""} provenance={nextEvent?.provenance} />
      <ProvenanceDrawer
        open={drawer === "priority"}
        onClose={() => setDrawer(null)}
        title={briefing.priority.title}
        provenance={{ origin: "Regra determinística + fixtures", last_checked: "2026-09-23T08:45:00-03:00", confidence: "alta", scope: "MedSyn" }}
      />
      <ProvenanceDrawer
        open={drawer === "alert"}
        onClose={() => setDrawer(null)}
        title={briefing.alerts[0].title}
        provenance={getEvent(briefing.alerts[0].evidence_event_ids[0])?.provenance}
      />
      {fixtures.events.map((ev) => (
        <ProvenanceDrawer key={ev.id} open={drawer === ev.id} onClose={() => setDrawer(null)} title={ev.title} provenance={ev.provenance} />
      ))}
    </div>
  );
}
