"use client";
import { useState, useRef, useEffect } from "react";
import { Badge, Card, Button, ProvenanceDrawer } from "@/components/ui/primitives";

type Msg = { role: "user" | "assistant"; text: string; provenance?: any; streaming?: boolean };

const starters = ["O que mudou? Tenho 45 minutos; o que adianto?", "Resumir conflito Academia × MedSyn", "Mostrar ideia CRIVO capturada"];

export default function ConversaPage() {
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: "assistant",
      text: "Olá, Victor. Estou no Gate 1 — só com dados DEMO fictícios, sem acesso real ao seu Calendar ou Gmail. Posso mostrar o briefing com fontes, as 2 alternativas do conflito e a captura vinculada ao CRIVO. O que deseja fazer?",
      provenance: { origin: "Fixtures + regra determinística", last_checked: "2026-09-23T08:47:00-03:00", confidence: "alta", scope: "pessoal" }
    }
  ]);
  const [input, setInput] = useState("");
  const [drawer, setDrawer] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  function send(text: string) {
    if (!text.trim()) return;
    const user: Msg = { role: "user", text };
    setMsgs((m) => [...m, user]);
    setInput("");
    setStreaming(true);
    // Simula streaming + cancelamento (Gate 1 mock)
    const answer: Msg = {
      role: "assistant",
      text: text.toLowerCase().includes("45")
        ? "Você tem 45 min antes da daily às 09:30. Recomendo: finalizar 1 slide da demo MedSyn (prioridade essencial). Evidência: entrega 19h depende deste artefato (fonte: Calendar 19h, Gmail orçamento). Alternativa curta: revisar orçamento SOFF (5 min). Nenhuma ação externa será feita sem sua aprovação."
        : text.toLowerCase().includes("conflito")
          ? "Conflito detectado: Academia 18h × Entrega 19h. 2 alternativas sem escrever no Calendar: (A) mover academia para 17h, (B) encurtar treino para 40min. Ambas são rascunhos com chave idempotente. Diga qual prefere e eu preparo o diff para a Central de aprovações."
          : "Ideia “triagem por similaridade semântica” capturada em 08:10, classificada como referência e vinculada ao projeto CRIVO. Não criei reunião nem e-mail. Você pode revisar em Inbox → Domínios → CRIVO. Quer adicionar detalhes?",
      provenance: { origin: "Fixtures DEMO", last_checked: "2026-09-23T08:47:00-03:00", confidence: "média", scope: "pessoal" }
    };
    let i = 0;
    const full = answer.text;
    answer.text = "";
    setMsgs((m) => [...m, answer]);
    const id = setInterval(() => {
      i += 8;
      setMsgs((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { ...answer, text: full.slice(0, i), streaming: i < full.length };
        return copy;
      });
      if (i >= full.length) {
        clearInterval(id);
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
    <div className="mx-auto flex h-[calc(100vh-64px-80px)] max-w-[880px] flex-col px-4 py-4 md:h-[calc(100vh-64px)] md:px-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-widest text-ink-faint">CONVERSA JARVIS</div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Perguntar ao JARVIS</h1>
          <p className="hidden text-sm text-ink-subtle md:block">Respostas com evidências e ações confirmáveis. Voz tem paridade com texto (placeholder Gate 1).</p>
        </div>
        <Badge tone="amber">DEMO · streaming mock</Badge>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {starters.map((s) => (
          <button
            key={s}
            onClick={() => send(s)}
            className="rounded-full border border-paper-border bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-paper-muted"
          >
            {s}
          </button>
        ))}
      </div>

      <Card className="mt-4 flex flex-1 flex-col overflow-hidden">
        <div ref={listRef} className="flex-1 overflow-auto p-4 md:p-6" role="log" aria-live="polite">
          <div className="space-y-4">
            {msgs.map((m, idx) => (
              <div key={idx} className={["flex gap-3", m.role === "user" ? "justify-end" : "justify-start"].join(" ")}>
                {m.role === "assistant" && <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-xs text-white">J</div>}
                <div className={["max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed", m.role === "user" ? "bg-ink text-white" : "bg-paper-muted text-ink"].join(" ")}>
                  <div>{m.text}</div>
                  {m.streaming && <span className="mt-1 inline-block h-2 w-2 animate-pulse rounded-full bg-ink-faint" aria-hidden />}
                  {m.role === "assistant" && m.provenance && (
                    <button onClick={() => setDrawer(idx)} className="mt-2 text-xs font-medium text-ink-faint underline decoration-ink/20 underline-offset-4 hover:decoration-ink">
                      ver fontes
                    </button>
                  )}
                </div>
                {m.role === "user" && <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-paper-muted text-xs">V</div>}
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
            className="flex items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Digite ou fale — ex: “O que mudou hoje?”"
              className="flex-1 rounded-full border border-paper-border bg-paper-muted px-4 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-ink focus:bg-white focus:outline-none"
              aria-label="Mensagem para o JARVIS"
            />
            <Button type="submit" disabled={streaming}>
              Enviar
            </Button>
            <Button type="button" variant="outline" aria-label="Voz — placeholder">
              🎙
            </Button>
            {streaming && (
              <Button type="button" variant="ghost" onClick={() => setStreaming(false)}>
                Cancelar
              </Button>
            )}
          </form>
          <div className="mt-2 flex items-center gap-2 text-xs text-ink-faint">
            <span className="inline-flex items-center gap-1 rounded-full bg-paper-muted px-2 py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden /> mock
            </span>
            Respostas sinalizadas como inferência quando necessário. Voz com fallback completo por texto.
          </div>
        </div>
      </Card>

      {msgs.map((m, i) => m.provenance && <ProvenanceDrawer key={i} open={drawer === i} onClose={() => setDrawer(null)} title="Proveniência da resposta" provenance={m.provenance} />)}
    </div>
  );
}
