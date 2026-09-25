import { useState } from "react";
import "./App.css";
import { loadSyntheticOutbox, saveSyntheticCapture, type SyntheticCapture } from "./synthetic-outbox";

const sections = ["Agora", "Conversa", "Inbox", "Missões"] as const;
type Section = (typeof sections)[number];
function App() {
  const [section, setSection] = useState<Section>("Agora");
  const [text, setText] = useState("");
  const [outbox, setOutbox] = useState<SyntheticCapture[]>(() => loadSyntheticOutbox(window.localStorage));
  const [notice, setNotice] = useState("");

  function saveCapture(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = saveSyntheticCapture(window.localStorage, text, new Date().toISOString(), crypto.randomUUID());
    if (!next) return;
    setOutbox(next);
    setText("");
    setNotice("Captura sintética salva neste navegador; nada foi enviado.");
  }

  return (
    <main className="mobile-shell">
      <header className="topbar"><span className="mark">JV</span><strong>JARVIS</strong><span className="synthetic">SOMENTE SINTÉTICO</span></header>
      <section className="content" aria-live="polite">
        <p className="eyebrow">CLIENTE ANDROID · PROTÓTIPO WEB</p>
        <h1>{section}</h1>
        {section === "Agora" && <article className="card"><span className="badge">DEMO LOCAL</span><h2>Uma interface móvel para o Victor OS.</h2><p>Sem contas conectadas, fontes reais ou sincronização em segundo plano.</p><button type="button" onClick={() => setSection("Inbox")}>Capturar uma ideia fictícia</button></article>}
        {section === "Conversa" && <article className="card"><span className="badge">SEM LLM</span><h2>Conversa sintética</h2><p>Este protótipo não envia mensagens a um modelo ou serviço externo.</p></article>}
        {section === "Inbox" && <article className="card"><span className="badge">OUTBOX LOCAL · ATÉ 20 ITENS</span><h2>Nova captura fictícia</h2><form onSubmit={saveCapture}><label htmlFor="capture-text">Texto</label><textarea id="capture-text" value={text} maxLength={500} onChange={(event) => setText(event.currentTarget.value)} placeholder="Escreva somente conteúdo de teste" /><button type="submit" disabled={!text.trim()}>Salvar localmente</button></form>{notice && <p role="status">{notice}</p>}<h3>Fila local ({outbox.length})</h3><ul>{outbox.map((item) => <li key={item.id}><span>{item.text}</span><small>fictício · {new Date(item.created_at).toLocaleString("pt-BR")}</small></li>)}</ul></article>}
        {section === "Missões" && <article className="card"><span className="badge">SIMULAÇÃO · CUSTO 0</span><h2>Revisar fontes fictícias</h2><ol><li>Capturar entradas sintéticas <small>Planejada</small></li><li>Montar contexto autorizado <small>Bloqueada</small></li><li>Preparar rascunho com evidências <small>Bloqueada</small></li></ol><p>Esta tela é ilustrativa e não executa tarefas.</p></article>}
      </section>
      <nav className="bottom-nav" aria-label="Navegação principal">{sections.map((item) => <button type="button" key={item} aria-current={section === item ? "page" : undefined} className={section === item ? "nav-item active" : "nav-item"} onClick={() => { setSection(item); setNotice(""); }}>{item}</button>)}</nav>
    </main>
  );
}

export default App;
