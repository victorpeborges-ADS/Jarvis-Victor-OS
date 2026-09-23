"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { fixtures, sensitivityLabel } from "@/lib/demo";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";

export default function DominiosPage() {
  const [active, setActive] = useState("todos");
  const scrollRef = useRef<HTMLDivElement>(null);
  const domains = fixtures.domains;
  const activeDomain = domains.find((d) => d.name === active || d.id === active);

  const eventsByDomain: Record<string, typeof fixtures.events> = {
    CRIVO: fixtures.events.filter((e) => e.provenance.scope.toLowerCase().includes("crivo") || e.title.toLowerCase().includes("crivo")),
    MedSyn: fixtures.events.filter((e) => e.title.includes("MedSyn")),
    Saúde: fixtures.events.filter((e) => e.title.includes("Academia")),
    Finanças: fixtures.events.filter((e) => e.title.includes("orçamento")),
    "Trabalho / CGMUR": fixtures.events.filter((e) => e.sensitivity === "internal" && e.event_type === "commitment").slice(0, 2)
  };

  // CRIVO sem eventos de calendário — mostra só capturas; evitar lista vazia enganosa misturando outros
  if (eventsByDomain.CRIVO.length === 0) {
    eventsByDomain.CRIVO = [];
  }

  const filteredEvents = active === "todos" ? fixtures.events : eventsByDomain[active] ?? [];
  const inboxFiltered = active === "todos" ? fixtures.inbox : fixtures.inbox.filter((i) => i.domain === active);

  function selectDomain(name: string) {
    setActive(name);
  }

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">DOMÍNIOS DA VIDA</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Domínios</h1>
          <p className="text-sm text-ink-subtle">Mesma memória, filtros distintos. Não misture escopos.</p>
        </div>
        <Badge tone="amber">DEMO · 8 domínios</Badge>
      </div>

      <div className="mt-4">
        <div className="mb-1 flex items-center justify-between text-[11px] text-ink-faint">
          <span>Deslize para ver todos os domínios</span>
          {activeDomain && <span className="font-medium text-ink">Filtro: {activeDomain.name}</span>}
        </div>
        <div ref={scrollRef} className="chip-scroll" role="tablist" aria-label="Filtrar por domínio">
          <button
            type="button"
            role="tab"
            aria-selected={active === "todos"}
            onClick={() => selectDomain("todos")}
            className={[
              "shrink-0 rounded-full px-4 py-2 text-sm font-medium",
              active === "todos" ? "bg-ink text-white" : "border border-paper-border bg-white text-ink hover:bg-paper-muted"
            ].join(" ")}
          >
            Todos
          </button>
          {domains.map((d) => (
            <button
              key={d.id}
              type="button"
              role="tab"
              aria-selected={active === d.name}
              onClick={() => selectDomain(d.name)}
              className={[
                "shrink-0 rounded-full px-4 py-2 text-sm font-medium",
                active === d.name ? "bg-ink text-white" : "border border-paper-border bg-white text-ink hover:bg-paper-muted"
              ].join(" ")}
            >
              {d.name}{" "}
              <span
                className={[
                  "ml-1 rounded-full px-1.5 py-0.5 text-xs",
                  active === d.name ? "bg-white/20 text-white" : "bg-paper-muted text-ink-faint"
                ].join(" ")}
              >
                {d.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {active !== "todos" && (
        <div className="mt-3 rounded-xl border border-paper-border bg-paper-muted/50 px-3 py-2 text-xs text-ink-subtle">
          Contexto ativo: <span className="font-medium text-ink">{active}</span>
          {activeDomain ? ` · ${activeDomain.count} item(ns) no índice` : ""}. Itens de outros domínios ficam ocultos neste filtro.
        </div>
      )}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink">Memória filtrada — {active === "todos" ? "visão ampla" : active}</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-subtle">
            {active === "CRIVO"
              ? "CRIVO concentra ideias/capturas. Eventos de calendário de outros escopos não aparecem aqui."
              : "Eventos e referências do domínio selecionado, com proveniência preservada."}
          </p>
          <div className="mt-4 space-y-2">
            {filteredEvents.length === 0 ? (
              <EmptyState
                title="Nada neste domínio hoje"
                description={
                  active === "CRIVO"
                    ? "Sem compromissos de calendário em CRIVO. Veja as capturas ao lado."
                    : "Este domínio não tem eventos hoje. Capture algo no Inbox se fizer sentido."
                }
                action={
                  <Link href="/inbox" className="inline-flex rounded-full bg-ink px-4 py-2 text-sm font-medium text-white">
                    Capturar ideia
                  </Link>
                }
              />
            ) : (
              filteredEvents.map((ev) => (
                <div key={ev.id} className="rounded-xl border border-paper-border bg-paper-muted px-3 py-2.5">
                  <div className="text-sm font-medium text-ink">{ev.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    {ev.provenance.origin} · {ev.provenance.confidence} · {sensitivityLabel(ev.sensitivity)}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink">Capturas vinculadas</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-subtle">Proveniência explícita, sem vazamento entre domínios sensíveis.</p>
          <div className="mt-4 space-y-2">
            {inboxFiltered.length === 0 ? (
              <div className="rounded-xl border border-dashed border-paper-border bg-paper-muted/50 px-4 py-6 text-center text-sm text-ink-subtle">
                Nenhuma captura neste domínio.
              </div>
            ) : (
              inboxFiltered.map((it) => (
                <div key={it.id} className="rounded-xl border border-paper-border bg-white px-3 py-3">
                  <div className="text-sm font-medium text-ink">{it.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    Tipo: {it.type} · Status: {it.status === "classified" ? "classificado" : it.status}
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="mt-4 rounded-xl bg-ink px-4 py-3 text-xs leading-relaxed text-white/80">
            Isolamento: um pedido pessoal <span className="font-semibold text-white">não recupera</span> docs MedSyn/MCID. Log sem PII.
          </div>
        </Card>
      </div>

      <Card className="mt-4 p-5">
        <h3 className="text-sm font-semibold text-ink">Como domínios protegem sua rotina</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {[
            { k: "Família/Fé", v: "Separado de MedSyn — sem cópia de dados sensíveis" },
            { k: "MedSyn", v: "Entregas e sprints com escopo próprio" },
            { k: "CRIVO", v: "Ideias ficam como referência até aprovação" }
          ].map((x) => (
            <div key={x.k} className="rounded-xl bg-paper-muted px-3 py-3">
              <div className="text-xs font-semibold text-ink">{x.k}</div>
              <div className="mt-1 text-xs leading-relaxed text-ink-subtle">{x.v}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
