"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { fixtures, sensitivityLabel } from "@/lib/demo";
import { capturesForDomain, countForDomain, domainName, eventsForDomain, isKnownDomainId, partitionByDomain } from "@/lib/domains";
import { DEMO_STORAGE_LIMITS, useDemoCaptures } from "@/lib/demo-inbox-store";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";

export default function DominiosPage() {
  const [active, setActive] = useState("todos");
  const domains = fixtures.domains;
  const { items: captures, ephemeral } = useDemoCaptures();
  const activeDomain = domains.find((d) => d.id === active);
  const { assigned: assignedEvents, unassigned } = partitionByDomain(fixtures.events);
  const filteredEvents = active === "todos" ? assignedEvents : eventsForDomain(fixtures.events, active);
  const inboxFiltered = active === "todos" ? captures.filter((item) => isKnownDomainId(item.domain_id)) : capturesForDomain(captures, active);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("dominio");
    if (requested && isKnownDomainId(requested)) setActive(requested);
  }, []);

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
        <div className="mb-1 text-[11px] text-ink-faint">Toque no domínio para isolar o contexto.</div>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Filtrar por domínio">
          <button
            type="button"
            role="tab"
            data-testid="domain-tab-todos"
            aria-selected={active === "todos"}
            onClick={() => setActive("todos")}
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
              data-testid={`domain-tab-${d.id}`}
              aria-selected={active === d.id}
              onClick={() => setActive(d.id)}
              className={[
                "shrink-0 rounded-full px-4 py-2 text-sm font-medium",
                active === d.id ? "bg-ink text-white" : "border border-paper-border bg-white text-ink hover:bg-paper-muted"
              ].join(" ")}
            >
              {d.name}{" "}
              <span
                className={[
                  "ml-1 rounded-full px-1.5 py-0.5 text-xs",
                  active === d.id ? "bg-white/20 text-white" : "bg-paper-muted text-ink-faint"
                ].join(" ")}
              >
                {countForDomain(d.id, fixtures.events, captures)}
              </span>
            </button>
          ))}
        </div>
      </div>

      {active !== "todos" && (
        <div className="mt-3 rounded-xl border border-paper-border bg-paper-muted/50 px-3 py-2 text-xs text-ink-subtle" data-testid="domain-context">
          Contexto ativo: <span className="font-medium text-ink">{activeDomain ? activeDomain.name : "desconhecido"}</span>
          . Itens de outros domínios ficam ocultos neste filtro. Sem compartilhamento automático.
        </div>
      )}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink">Memória filtrada — {active === "todos" ? "visão ampla" : domainName(active)}</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-subtle">
            Filtro por identificador de domínio. Título, confidencialidade e proveniência não mudam o escopo.
          </p>
          <div className="mt-4 space-y-2" data-testid="domain-events">
            {filteredEvents.length === 0 ? (
              <EmptyState
                title="Nada neste domínio hoje"
                description="Este domínio não tem eventos com este identificador. Capture algo no Inbox se fizer sentido."
                action={
                  <Link href="/inbox" className="inline-flex rounded-full bg-ink px-4 py-2 text-sm font-medium text-white">
                    Capturar ideia
                  </Link>
                }
              />
            ) : (
              filteredEvents.map((ev) => (
                <div
                  key={ev.id}
                  data-testid="domain-event"
                  data-event-id={ev.id}
                  data-domain-id={ev.domain_id ?? ""}
                  className="rounded-xl border border-paper-border bg-paper-muted px-3 py-2.5"
                >
                  <div className="text-sm font-medium text-ink">{ev.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    Domínio: {domainName(ev.domain_id)} · Confidencialidade: {sensitivityLabel(ev.sensitivity)} · Origem: {ev.provenance.origin}
                  </div>
                </div>
              ))
            )}
          </div>
          {active === "todos" && unassigned.length > 0 && (
            <div className="mt-4 rounded-xl border border-dashed border-paper-border px-3 py-3" data-testid="domain-unassigned">
              <div className="text-xs font-semibold text-ink">Fora dos 8 domínios · {unassigned.length}</div>
              <p className="mt-1 text-xs leading-relaxed text-ink-subtle">
                Sem domain_id conhecido. Não entram em nenhum filtro e não são compartilhados.
              </p>
              <ul className="mt-2 space-y-1">
                {unassigned.map((ev) => (
                  <li key={ev.id} className="text-xs text-ink-subtle" data-testid="unassigned-event" data-event-id={ev.id}>
                    {ev.title}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink">Capturas vinculadas</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-subtle">Mesma lista do Inbox (armazenamento local DEMO). Sem vazamento entre domínios.</p>
          <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">{DEMO_STORAGE_LIMITS}</p>
          {ephemeral && (
            <p className="mt-1 text-[11px] leading-relaxed text-amber-800" data-testid="ephemeral-warning">
              Estas capturas extras estão só nesta sessão e serão perdidas ao recarregar.
            </p>
          )}
          <div className="mt-4 space-y-2" data-testid="domain-captures">
            {inboxFiltered.length === 0 ? (
              <div className="rounded-xl border border-dashed border-paper-border bg-paper-muted/50 px-4 py-6 text-center text-sm text-ink-subtle">
                Nenhuma captura neste domínio.
              </div>
            ) : (
              inboxFiltered.map((it) => (
                <div
                  key={it.id}
                  data-testid="domain-capture"
                  data-capture-id={it.id}
                  data-domain-id={it.domain_id}
                  className="rounded-xl border border-paper-border bg-white px-3 py-3"
                >
                  <div className="text-sm font-medium text-ink">{it.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    Domínio: {domainName(it.domain_id)} · Tipo: {it.type} · Status: {it.status === "classified" ? "classificado" : it.status}
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
