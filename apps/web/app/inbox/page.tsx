"use client";
import { useState } from "react";
import Link from "next/link";
import { fixtures, inboxStatusLabel, formatTimeH } from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer, EmptyState } from "@/components/ui/primitives";

type InboxType = "tarefa" | "evento" | "referência" | "projeto" | "pessoa" | "nota";

export default function InboxPage() {
  const [text, setText] = useState("");
  const [type, setType] = useState<InboxType>("referência");
  const [domain, setDomain] = useState("CRIVO");
  const [items, setItems] = useState(fixtures.inbox);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("todos");
  const [feedback, setFeedback] = useState<string | null>(null);

  function handleCapture() {
    if (!text.trim()) return;
    const title = text.slice(0, 80);
    const novo: (typeof fixtures.inbox)[number] = {
      id: `inb_${Date.now()}`,
      type: type,
      title,
      domain,
      entity_ref: domain === "CRIVO" ? "ent_projeto_crivo" : "",
      status: "classified",
      created_at: new Date().toISOString(),
      evidence: "Classificada localmente — sem criação de evento/e-mail externo"
    };
    setItems([novo, ...items]);
    setText("");
    setFeedback(`Salvo como ${type} em ${domain}. Nenhuma reunião ou e-mail foi criado — revisão humana preservada.`);
  }

  const filtered = filter === "todos" ? items : items.filter((i) => i.domain === filter);

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">INBOX · CAPTURA RÁPIDA</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Caixa de entrada</h1>
          <p className="text-sm text-ink-subtle">Capte texto ou link. Classificamos sem criar reunião ou e-mail sem aprovação.</p>
        </div>
        <Badge tone="amber">DEMO</Badge>
      </div>

      {feedback && (
        <div
          role="status"
          className="mt-4 flex items-start justify-between gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900 ring-1 ring-emerald-200"
        >
          <div>
            <div className="font-medium">Captura classificada e salva</div>
            <div className="mt-0.5 text-xs leading-relaxed text-emerald-800">{feedback}</div>
          </div>
          <button type="button" className="shrink-0 text-xs font-medium underline" onClick={() => setFeedback(null)} aria-label="Dispensar feedback">
            Ok
          </button>
        </div>
      )}

      <Card className="mt-6 p-5 md:p-6">
        <div className="flex items-center gap-2 text-xs font-semibold tracking-widest text-ink-faint">
          <span aria-hidden>＋</span> NOVA CAPTURA — JORNADA 3
        </div>

        <div className="mt-3">
          <label htmlFor="capture" className="text-sm font-medium text-ink">
            O que deseja capturar?
          </label>
          <textarea
            id="capture"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 280))}
            placeholder="Ex: Ideia CRIVO — triagem por similaridade semântica com embeddings locais..."
            rows={3}
            className="mt-1 w-full rounded-2xl border border-paper-border bg-paper-muted px-4 py-3 text-sm leading-relaxed text-ink placeholder:text-ink-faint focus:border-ink focus:bg-white focus:outline-none"
          />
          <div className="mt-2 text-xs text-ink-faint">{text.length}/280 · revisado por humano antes de virar ação externa</div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="inbox-type" className="text-xs font-medium text-ink">
              Classificar como
            </label>
            <select
              id="inbox-type"
              value={type}
              onChange={(e) => setType(e.target.value as InboxType)}
              className="mt-1 w-full rounded-full border border-paper-border bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none"
            >
              <option value="tarefa">tarefa</option>
              <option value="evento">evento</option>
              <option value="referência">referência</option>
              <option value="projeto">projeto</option>
              <option value="pessoa">pessoa</option>
              <option value="nota">nota</option>
            </select>
          </div>
          <div>
            <label htmlFor="inbox-domain" className="text-xs font-medium text-ink">
              Domínio
            </label>
            <select
              id="inbox-domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="mt-1 w-full rounded-full border border-paper-border bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none"
            >
              <option>CRIVO</option>
              <option>MedSyn</option>
              <option>Trabalho / CGMUR</option>
              <option>Saúde</option>
              <option>Finanças</option>
            </select>
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button onClick={handleCapture} disabled={!text.trim()} className="w-full sm:w-auto sm:min-w-[200px]" size="lg">
            Classificar e salvar
          </Button>
          <span
            className="inline-flex items-center justify-center rounded-full border border-dashed border-paper-border px-3 py-2 text-xs text-ink-faint"
            title="Voz virá no Gate 5 — paridade com texto"
          >
            🎙 Voz — em breve (use texto)
          </span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-ink-faint">
          Não cria automaticamente reunião, e-mail nem afeta backlog institucional. Vincula ao domínio escolhido com revisão humana.
        </p>
      </Card>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold text-ink">Itens capturados · {filtered.length}</h2>
        <div className="chip-scroll" role="toolbar" aria-label="Filtrar por domínio">
          {["todos", "CRIVO", "MedSyn"].map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={[
                "shrink-0 rounded-full px-3 py-1 text-xs font-medium",
                filter === f ? "bg-ink text-white" : "bg-paper-muted text-ink-subtle hover:bg-paper-border"
              ].join(" ")}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 space-y-3">
        {filtered.length === 0 ? (
          <EmptyState
            title="Nenhum item neste filtro"
            description="Tente outro domínio ou capture uma nova ideia acima. Nada é enviado para fora sem sua aprovação."
            action={
              filter !== "todos" ? (
                <Button size="sm" variant="outline" onClick={() => setFilter("todos")}>
                  Ver todos
                </Button>
              ) : undefined
            }
          />
        ) : (
          filtered.map((it) => (
            <Card key={it.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-paper-muted px-2 py-1 text-xs font-medium text-ink">{it.type}</span>
                    <span className="rounded-full bg-violet-50 px-2 py-1 text-xs font-medium text-violet-700 ring-1 ring-violet-200">{it.domain}</span>
                    <Badge tone="emerald">{inboxStatusLabel(it.status)}</Badge>
                  </div>
                  <div className="mt-2 text-sm font-medium leading-tight text-ink">{it.title}</div>
                  <div className="mt-1 text-xs leading-relaxed text-ink-subtle">{it.evidence}</div>
                </div>
                <button
                  type="button"
                  onClick={() => setDrawer(it.id)}
                  className="shrink-0 rounded-full border border-paper-border bg-white px-3 py-1 text-xs font-medium text-ink hover:bg-paper-muted"
                >
                  fontes
                </button>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                <span>{formatTimeH(it.created_at)} · {new Date(it.created_at).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" })}</span>
                <span>·</span>
                <Link href="/dominios" className="font-medium text-ink underline decoration-ink/20 underline-offset-4">
                  Ver em Domínios →
                </Link>
              </div>
            </Card>
          ))
        )}
      </div>

      {filtered.map((it) => (
        <ProvenanceDrawer
          key={it.id}
          open={drawer === it.id}
          onClose={() => setDrawer(null)}
          title={it.title}
          provenance={{
            origin: "Inbox local + fixtures",
            last_checked: it.created_at,
            confidence: "média",
            scope: it.domain,
            note: "Vinculada a ent_projeto_crivo quando domínio = CRIVO"
          }}
        />
      ))}
    </div>
  );
}
