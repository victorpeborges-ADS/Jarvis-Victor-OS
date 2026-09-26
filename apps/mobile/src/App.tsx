import { useState } from "react";
import "./App.css";
import { loadSyntheticOutbox, saveSyntheticCapture, OUTBOX_KEY, type SyntheticCapture } from "./synthetic-outbox";

const bottomSections = ["Agora", "Inbox", "Missões", "Aprovações", "Mais"] as const;
type Section = (typeof bottomSections)[number] | "Fontes" | "Integrações" | "Configurações";
function App() {
  const [section, setSection] = useState<Section>("Agora");
  const [text, setText] = useState("");
  const [outbox, setOutbox] = useState<SyntheticCapture[]>(() => loadSyntheticOutbox(window.localStorage));
  const [notice, setNotice] = useState("");
  const [syntheticConfirmed, setSyntheticConfirmed] = useState(false);

  function saveCapture(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!syntheticConfirmed) return;
    try {
      const next = saveSyntheticCapture(window.localStorage, text, new Date().toISOString(), crypto.randomUUID());
      if (!next) return;
      setOutbox(next); setText(""); setSyntheticConfirmed(false);
      setNotice("Captura fictícia salva neste aplicativo; nada foi enviado.");
    } catch {
      setNotice("Não foi possível salvar a captura. O texto permanece no campo para recuperação.");
    }
  }

  return (
    <main className="mobile-shell">
      <header className="topbar"><span className="mark">JV</span><strong>JARVIS</strong><span className="synthetic">SOMENTE SINTÉTICO</span></header>
      <section className="content" aria-live="polite">
        <p className="eyebrow">CLIENTE ANDROID · PROTÓTIPO WEB</p>
        <h1>{section}</h1>
        {section === "Agora" && <article className="card"><span className="badge">DEMO LOCAL</span><h2>Uma interface móvel para o Victor OS.</h2><p>Sem contas conectadas, fontes reais ou sincronização em segundo plano.</p><button type="button" onClick={() => setSection("Inbox")}>Capturar uma ideia fictícia</button></article>}
        {section === "Inbox" && <article className="card"><span className="badge">FILA LOCAL · ATÉ 20 ITENS</span><h2>Nova captura fictícia</h2><form onSubmit={saveCapture}><label htmlFor="capture-text">Texto de teste</label><textarea id="capture-text" value={text} maxLength={500} onChange={(event) => setText(event.currentTarget.value)} placeholder="Escreva somente conteúdo de teste" /><label className="confirm"><input type="checkbox" checked={syntheticConfirmed} onChange={(event) => setSyntheticConfirmed(event.currentTarget.checked)} /> Confirmo que o texto é fictício e pode ser salvo neste aparelho.</label><button type="submit" disabled={!text.trim() || !syntheticConfirmed}>Salvar localmente</button></form>{notice && <p role="status">{notice}</p>}<h3>Fila local ({outbox.length})</h3><ul>{outbox.map((item) => <li key={item.id}><span>{item.text}</span><small>fictício · {new Date(item.created_at).toLocaleString("pt-BR")}</small></li>)}</ul></article>}
        {section === "Missões" && <article className="card"><span className="badge">SIMULAÇÃO · CUSTO 0</span><h2>Revisar fontes fictícias</h2><ol><li>Capturar entradas sintéticas <small>Planejada</small></li><li>Montar contexto autorizado <small>Bloqueada</small></li><li>Preparar rascunho com evidências <small>Bloqueada</small></li></ol><p>Esta tela é ilustrativa e não executa tarefas.</p></article>}
        {section === "Aprovações" && <article className="card"><span className="badge">API NÃO CONECTADA</span><h2>Sem decisões neste aparelho</h2><p>A fila persistente de revisão está na API local da web. Este cliente não concede permissões nem simula aprovações.</p></article>}
        {section === "Mais" && <article className="card"><span className="badge">CAPACIDADES DECLARADAS</span><h2>Explorar com clareza</h2><div className="more-actions"><button type="button" onClick={() => setSection("Fontes")}>Fontes e contexto</button><button type="button" onClick={() => setSection("Integrações")}>Integrações</button><button type="button" onClick={() => setSection("Configurações")}>Privacidade e diagnóstico</button></div></article>}
        {section === "Fontes" && <article className="card"><span className="badge">SEM FONTE PESSOAL</span><h2>Contexto ainda não importado</h2><p>Somente as capturas fictícias desta fila local estão disponíveis. Nenhum arquivo, calendário ou documento do aparelho foi lido. A seleção explícita de arquivos aguarda um próximo gate.</p><button type="button" onClick={() => setSection("Mais")}>Voltar</button></article>}
        {section === "Integrações" && <article className="card"><span className="badge">NÃO CONFIGURADO</span><h2>Conexões desativadas</h2><p>Calendar, Gmail, Drive, GitHub e modelos de IA não estão conectados neste cliente. Nenhum OAuth ou serviço pago foi iniciado.</p><button type="button" onClick={() => setSection("Mais")}>Voltar</button></article>}
        {section === "Configurações" && <article className="card"><span className="badge">DEMO OFFLINE</span><h2>Privacidade local</h2><p>Sem sincronização, API remota ou observação em segundo plano. As capturas fictícias ficam no armazenamento deste aplicativo.</p><button type="button" disabled={outbox.length === 0} onClick={() => { window.localStorage.removeItem(OUTBOX_KEY); setOutbox([]); setNotice("Capturas fictícias locais removidas."); }}>Apagar capturas fictícias</button><button type="button" onClick={() => setSection("Mais")}>Voltar</button></article>}
      </section>
      <nav className="bottom-nav" aria-label="Navegação principal">{bottomSections.map((item) => <button type="button" key={item} aria-current={section === item || (item === "Mais" && ["Fontes", "Integrações", "Configurações"].includes(section)) ? "page" : undefined} className={section === item || (item === "Mais" && ["Fontes", "Integrações", "Configurações"].includes(section)) ? "nav-item active" : "nav-item"} onClick={() => { setSection(item); setNotice(""); }}>{item}</button>)}</nav>
    </main>
  );
}

export default App;
