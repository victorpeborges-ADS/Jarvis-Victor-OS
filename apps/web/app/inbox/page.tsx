"use client";
import { useState } from "react";
import Link from "next/link";
import { fixtures } from "@/lib/demo";
import { Badge, Card, Button, ProvenanceDrawer, EmptyState } from "@/components/ui/primitives";

type InboxType = "tarefa" | "evento" | "referência" | "projeto" | "pessoa" | "nota";

export default function InboxPage() {
  const [text, setText] = useState("");
  const [type, setType] = useState<InboxType>("referência");
  const [domain, setDomain] = useState("CRIVO");
  const [items, setItems] = useState(fixtures.inbox);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("todos");

  function handleCapture() {
    if (!text.trim()) return;
    const novo: any = {
      id: `inb_${Date.now()}`,
      type: type,
      title: text.slice(0, 80),
      domain,
      entity_ref: domain === "CRIVO" ? "ent_projeto_crivo" : undefined,
      status: "classified",
      created_at: new Date().toISOString(),
      evidence: "Classificada localmente — sem criação de evento/e-mail externo"
    };
    setItems([novo, ...items]);
    setText("");
  }

  const filtered = filter === "todos" ? items : items.filter((i: any) => i.domain === filter);

  return (
    <div className="mx-auto max-w-[880px] px-4 py-6 md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">INBOX · CAPTURA RÁPIDA</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Caixa de entrada</h1>
          <p className="text-sm text-ink-subtle">Capte texto, voz, link ou arquivo. Classificamos sem criar reunião ou e-mail sem aprovação.</p>
        </div>
        <Badge tone="amber">DEMO</Badge>
      </div>

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
            onChange={(e) => setText(e.target.value)}
            placeholder="Ex: Ideia CRIVO — triagem por similaridade semântica com embeddings locais..."
            rows={3}
            className="mt-1 w-full rounded-2xl border border-paper-border bg-paper-muted px-4 py-3 text-sm leading-relaxed text-ink placeholder:text-ink-faint focus:border-ink focus:bg-white focus:outline-none"
          />
          <div className="mt-2 text-xs text-ink-faint">{text.length}/280 · revisado por humano antes de virar ação externa</div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div>
            <label className="text-xs font-medium text-ink">Classificar como</label>
            <select value={type} onChange={(e) => setType(e.target.value as any)} className="mt-1 w-full rounded-full border border-paper-border bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none">
              <option value="tarefa">tarefa</option>
              <option value="evento">evento</option>
              <option value="referência">referência</option>
              <option value="projeto">projeto</option>
              <option value="pessoa">pessoa</option>
              <option value="nota">nota</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-ink">Domínio</label>
            <select value={domain} onChange={(e) => setDomain(e.target.value)} className="mt-1 w-full rounded-full border border-paper-border bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none">
              <option>CRIVO</option>
              <option>MedSyn</option>
              <option>Trabalho / CGMUR</option>
              <option>Saúde</option>
              <option>Finanças</option>
            </select>
          </div>
          <div className="flex items-end gap-2">
            <Button onClick={handleCapture} className="flex-1">
              Classificar e salvar
            </Button>
            <Button variant="outline" aria-label="Voz">
              🎙
            </Button>
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-ink-faint">Jornada 3: captura não cria automaticamente reunião, e-mail nem afeta backlog institucional. Vincula ao projeto CRIVO com revisão humana.</p>
      </Card>

      <div className="mt-6 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">Itens capturados · {filtered.length}</h2>
        <div className="flex gap-1.5">
          {["todos", "CRIVO", "MedSyn"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={["rounded-full px-3 py-1 text-xs font-medium", filter === f ? "bg-ink text-white" : "bg-paper-muted text-ink-subtle hover:bg-paper-border"].join(" ")}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 space-y-3">
        {filtered.length === 0 ? (
          <EmptyState title="Nenhum item neste filtro" description="Tente outro domínio ou capture uma nova ideia." />
        ) : (
          filtered.map((it: any) => (
            <Card key={it.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-paper-muted px-2 py-1 text-xs font-medium text-ink">{it.type}</span>
                    <span className="rounded-full bg-violet-50 px-2 py-1 text-xs font-medium text-violet-700 ring-1 ring-violet-200">{it.domain}</span>
                    <Badge tone="emerald">{it.status}</Badge>
                  </div>
                  <div className="mt-2 text-sm font-medium leading-tight text-ink">{it.title}</div>
                  <div className="mt-1 text-xs leading-relaxed text-ink-subtle">{it.evidence}</div>
                </div>
                <button onClick={() => setDrawer(it.id)} className="shrink-0 rounded-full border border-paper-border bg-white px-3 py-1 text-xs font-medium text-ink hover:bg-paper-muted">
                  fontes
                </button>
              </div>
              <div className="mt-3 flex items-center gap-2 text-xs text-ink-faint">
                <span>{new Date(it.created_at).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}</span>
                <span>·</span>
                <Link href="/dominios" className="font-medium text-ink underline decoration-ink/20 underline-offset-4">
                  Ver em Domínios →
                </Link>
              </div>
            </Card>
          ))
        )}
      </div>

      {filtered.map((it: any) => (
        <ProvenanceDrawer
          key={it.id}
          open={drawer === it.id}
          onClose={() => setDrawer(null)}
          title={it.title}
          provenance={{ origin: "Inbox local + fixtures", last_checked: it.created_at, confidence: "média", scope: it.domain, note: "Vinculada a ent_projeto_crivo quando domínio = CRIVO" }}
        />
      ))}
    </div>
  );
}
