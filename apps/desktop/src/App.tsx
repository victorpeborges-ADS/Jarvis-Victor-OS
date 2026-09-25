import { useState } from "react";
import "./App.css";

const sections = ["Agora", "Conversa", "Missões"] as const;
type Section = (typeof sections)[number];

function App() {
  const [section, setSection] = useState<Section>("Agora");

  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand" aria-label="JARVIS">
          <span className="mark">JV</span>
          <span>JARVIS</span>
        </div>
        <nav aria-label="Seções do JARVIS">
          {sections.map((item) => (
            <button
              aria-current={section === item ? "page" : undefined}
              className={section === item ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => setSection(item)}
              type="button"
            >
              {item}
            </button>
          ))}
        </nav>
        <p className="rail-note">Somente dados fictícios</p>
      </aside>

      <section className="content" aria-live="polite">
        <div className="eyebrow">POC DESKTOP · 100% SINTÉTICA</div>
        <h1>{section}</h1>
        {section === "Agora" && (
          <article className="card">
            <p className="badge">DEMO LOCAL</p>
            <h2>Seu espaço de trabalho começa aqui.</h2>
            <p>Nenhuma fonte real está conectada. Esta tela usa conteúdo fictício e não acessa contas ou serviços.</p>
          </article>
        )}
        {section === "Conversa" && (
          <article className="card">
            <p className="badge">RASCUNHO LOCAL</p>
            <h2>Conversa sintética</h2>
            <p>O roteador de linguagem não está conectado. Nenhum texto foi enviado a um modelo.</p>
          </article>
        )}
        {section === "Missões" && (
          <article className="card">
            <p className="badge">SIMULAÇÃO · CUSTO 0</p>
            <h2>Revisar fontes fictícias</h2>
            <ol>
              <li><span>Capturar entradas sintéticas</span><span>Planejada</span></li>
              <li><span>Montar contexto autorizado</span><span>Bloqueada</span></li>
              <li><span>Preparar rascunho com evidências</span><span>Bloqueada</span></li>
            </ol>
            <p>Este scaffold não executa tarefas nem grava dados.</p>
          </article>
        )}
      </section>
    </main>
  );
}

export default App;
