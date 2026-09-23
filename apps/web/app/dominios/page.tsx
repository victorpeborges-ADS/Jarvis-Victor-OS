"use client";
import { useState } from "react";
import Link from "next/link";
import { fixtures } from "@/lib/demo";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";

export default function DominiosPage() {
  const [active, setActive] = useState("todos");
  const domains = fixtures.domains;
  const activeDomain = domains.find((d: any) => d.name === active || d.id === active);

  const eventsByDomain: Record<string, any[]> = {
    "CRIVO": fixtures.events.filter(() => true).slice(0, 1),
    "MedSyn": fixtures.events.filter((e: any) => e.title.includes("MedSyn")),
    "Saúde": fixtures.events.filter((e: any) => e.title.includes("Academia")),
    "Finanças": fixtures.events.filter((e: any) => e.title.includes("orçamento")),
    "Trabalho / CGMUR": fixtures.events.slice(0, 2)
  };

  const filteredEvents = active === "todos" ? fixtures.events : eventsByDomain[active] ?? [];
  const inboxFiltered = active === "todos" ? fixtures.inbox : fixtures.inbox.filter((i: any) => i.domain === active);

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">DOMÍNIOS DA VIDA</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Domínios</h1>
          <p className="text-sm text-ink-subtle">Mesma memória, filtros distintos. Não são apps concorrentes.</p>
        </div>
        <Badge tone="amber">DEMO · 8 domínios</Badge>
      </div>

      <div className="mt-4 flex gap-2 overflow-auto pb-2">
        <button onClick={() => setActive("todos")} className={["shrink-0 rounded-full px-4 py-2 text-sm font-medium", active === "todos" ? "bg-ink text-white" : "border border-paper-border bg-white text-ink hover:bg-paper-muted"].join(" ")}>
          Todos
        </button>
        {domains.map((d: any) => (
          <button
            key={d.id}
            onClick={() => setActive(d.name)}
            className={["shrink-0 rounded-full px-4 py-2 text-sm font-medium", active === d.name ? "bg-ink text-white" : "border border-paper-border bg-white text-ink hover:bg-paper-muted"].join(" ")}
          >
            {d.name} <span className={["ml-1 rounded-full px-1.5 py-0.5 text-xs", active === d.name ? "bg-white/20 text-white" : "bg-paper-muted text-ink-faint"].join(" ")}>{d.count}</span>
          </button>
        ))}
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink">Memória filtrada — {active === "todos" ? "visão ampla" : active}</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-subtle">
            {active === "CRIVO" ? "Ideias de CRIVO vinculadas a ent_projeto_crivo, sem criar reunião automática." : "Eventos, tarefas e referências filtrados por domínio com proveniência preservada."}
          </p>
          <div className="mt-4 space-y-2">
            {filteredEvents.length === 0 ? (
              <EmptyState title="Nada aqui ainda" description="Este domínio não tem eventos hoje. Tente capturar algo no Inbox." action={<Link href="/inbox" className="inline-flex rounded-full bg-ink px-4 py-2 text-sm font-medium text-white">Capturar ideia</Link>} />
            ) : (
              filteredEvents.map((ev: any) => (
                <div key={ev.id} className="rounded-xl border border-paper-border bg-paper-muted px-3 py-2.5">
                  <div className="text-sm font-medium text-ink">{ev.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    {ev.provenance.origin} · {ev.provenance.confidence} · {ev.sensitivity}
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
              <div className="rounded-xl border border-dashed border-paper-border bg-paper-muted/50 px-4 py-6 text-center text-sm text-ink-subtle">Nenhuma captura neste domínio.</div>
            ) : (
              inboxFiltered.map((it: any) => (
                <div key={it.id} className="rounded-xl border border-paper-border bg-white px-3 py-3">
                  <div className="text-sm font-medium text-ink">{it.title}</div>
                  <div className="mt-1 text-xs text-ink-subtle">
                    Tipo: {it.type} · Status: {it.status}
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
