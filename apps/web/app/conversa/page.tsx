"use client";
import { useState, useRef, useEffect } from "react";
import { Badge, Card, Button, ProvenanceDrawer } from "@/components/ui/primitives";

type Msg = { role: "user" | "assistant"; text: string; provenance?: Record<string, string>; streaming?: boolean };

const starters = [
  { label: "Briefing com fontes", prompt: "O que mudou? Tenho 45 minutos; o que adianto?" },
  { label: "Conflito Academia × MedSyn", prompt: "Resumir conflito Academia × MedSyn" },
  { label: "Ideia CRIVO capturada", prompt: "Mostrar ideia CRIVO capturada" }
];

export default function ConversaPage() {
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: "assistant",
      text: "Olá, Victor. Estou no Gate 1 — só com dados DEMO fictícios, sem acesso real ao Calendar ou Gmail. Posso mostrar o briefing com fontes, as 2 alternativas do conflito e a captura vinculada ao CRIVO. Respostas são regras + fixtures, não um modelo de linguagem ativo.",
      provenance: { origin: "Fixtures + regra determinística", last_checked: "2026-09-23T08:47:00-03:00", confidence: "alta", scope: "pessoal" }
    }
  ]);
  const [input, setInput] = useState("");
  const [drawer, setDrawer] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [composerExpanded, setComposerExpanded] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  function cancelStream() {
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = null;
    setStreaming(false);
  }

  function send(text: string) {
    if (!text.trim() || streaming) return;
    const user: Msg = { role: "user", text };
    setMsgs((m) => [...m, user]);
    setInput("");
    setComposerExpanded(false);
    setStreaming(true);

    const answer: Msg = {
      role: "assistant",
      text: text.toLowerCase().includes("45")
        ? "Você tem 45 min antes da daily às 09h30 (relógio DEMO). Recomendo: finalizar 1 slide da demo MedSyn (prioridade essencial). Evidência: entrega 19h depende deste artefato. Alternativa curta: revisar orçamento SOFF (5 min). Nenhuma ação externa será feita sem sua aprovação."
        : text.toLowerCase().includes("conflito")
          ? "Conflito detectado: Academia 18h × Entrega 19h. 2 alternativas sem escrever no Calendar: (A) mover academia para 17h, (B) encurtar treino para 40min. Ambas são rascunhos. Diga qual prefere e prepare o diff em Aprovações."
          : "Ideia “triagem por similaridade semântica” capturada às 08h10, classificada como referência e vinculada ao projeto CRIVO. Não criei reunião nem e-mail. Revise em Inbox → Domínios → CRIVO.",
      provenance: { origin: "Fixtures DEMO (não LLM)", last_checked: "2026-09-23T08:47:00-03:00", confidence: "média", scope: "pessoal" }
    };
    let i = 0;
    const full = answer.text;
    answer.text = "";
    setMsgs((m) => [...m, answer]);
    intervalRef.current = setInterval(() => {
      i += 8;
      setMsgs((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { ...answer, text: full.slice(0, i), streaming: i < full.length };
        return copy;
      });
      if (i >= full.length) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        intervalRef.current = null;
        setStreaming(false);
        setMsgs((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { ...copy[copy.length - 1], streaming: false };
          return copy;
        });
      }
    }, 30);
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-64px-var(--bottom-nav-height))] max-w-[880px] flex-col px-4 py-4 md:min-h-[calc(100vh-64px)] md:px-8">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CONVERSA JARVIS</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Perguntar ao JARVIS</h1>
          <p className="mt-0.5 text-sm text-ink-subtle">Respostas com evidências e ações confirmáveis. Gate 1: fixtures, não LLM.</p>
        </div>
        <Badge tone="amber">DEMO · respostas simuladas</Badge>
      </div>

      {msgs.length <= 1 && (
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Sugestões úteis">
          {starters.map((s) => (
            <button
              key={s.prompt}
              type="button"
              onClick={() => send(s.prompt)}
              disabled={streaming}
              className="rounded-full border border-paper-border bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-paper-muted disabled:opacity-50"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      <Card className="mt-4 flex min-h-[280px] flex-1 flex-col overflow-hidden">
        <div ref={listRef} className="flex-1 overflow-auto p-4 md:p-6" role="log" aria-live="polite">
          <div className="space-y-4">
            {msgs.map((m, idx) => (
              <div key={idx} className={["flex gap-3", m.role === "user" ? "justify-end" : "justify-start"].join(" ")}>
                {m.role === "assistant" && (
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-xs text-white">J</div>
                )}
                <div
                  className={[
                    "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                    m.role === "user" ? "bg-ink text-white" : "bg-paper-muted text-ink"
                  ].join(" ")}
                >
                  <div>{m.text}</div>
                  {m.streaming && <span className="mt-1 inline-block h-2 w-2 animate-pulse rounded-full bg-ink-faint" aria-hidden />}
                  {m.role === "assistant" && m.provenance && !m.streaming && (
                    <button
                      type="button"
                      onClick={() => setDrawer(idx)}
                      className="mt-2 text-xs font-medium text-ink-muted underline decoration-ink/20 underline-offset-4 hover:decoration-ink"
                    >
                      ver fontes
                    </button>
                  )}
                </div>
                {m.role === "user" && (
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-paper-muted text-xs">V</div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="border-t border-paper-border bg-white p-3 md:p-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex flex-col gap-2"
          >
            <label htmlFor="jarvis-msg" className="sr-only">
              Mensagem para o JARVIS
            </label>
            <textarea
              id="jarvis-msg"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onFocus={() => setComposerExpanded(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={composerExpanded || input.length > 60 ? 3 : 1}
              placeholder='Ex.: "O que mudou hoje?"'
              className="w-full resize-none rounded-2xl border border-paper-border bg-paper-muted px-4 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-ink focus:bg-white "
              aria-label="Mensagem para o JARVIS"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={streaming || !input.trim()}>
                Enviar
              </Button>
              {streaming && (
                <Button type="button" variant="ghost" onClick={cancelStream}>
                  Cancelar
                </Button>
              )}
              <span className="text-xs text-ink-faint">Enter envia · Shift+Enter nova linha</span>
            </div>
          </form>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-1 text-amber-800 ring-1 ring-amber-200">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden /> simulação · sem LLM
            </span>
            Voz ainda não disponível — use texto (paridade planejada para Gate 5).
          </div>
        </div>
      </Card>

      {msgs.map(
        (m, i) =>
          m.provenance && (
            <ProvenanceDrawer
              key={i}
              open={drawer === i}
              onClose={() => setDrawer(null)}
              title="Proveniência da resposta"
              provenance={m.provenance}
            />
          )
      )}
    </div>
  );
}
