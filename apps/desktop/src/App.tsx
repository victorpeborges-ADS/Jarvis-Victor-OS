import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import "./App.css";
import { executeRuntimeCommand, parseRuntimeEnvelope, parseTransportSnapshot } from "./runtimeCommand";
import type { RuntimeEnvelope, RuntimeState, RuntimeCommand, TransportSnapshot, TransportState } from "./runtimeCommand";

const STORAGE_KEY = "jarvis-desktop-demo-captures-v1";
const sections = ["Agora", "Inbox", "Missões", "Aprovações", "Runtime local", "Configurações"] as const;
type Section = (typeof sections)[number];
type Capture = { id: string; text: string; created_at: string };

const runtimeStateLabels: Record<RuntimeState, string> = {
  STOPPED: "Parado",
  STARTING: "Iniciando",
  READY: "Pronto",
  STOPPING: "Encerrando",
  FAILED: "Falhou",
  CRASHED: "Interrompido",
};

const transportStateLabels: Record<TransportState, string> = {
  DISCONNECTED: "Desconectado",
  DISCOVERING: "Localizando canal",
  PROVING_INSTANCE: "Validando instância",
  READY: "Autenticado",
  INCOMPATIBLE: "Versão incompatível",
  FAILED: "Falhou",
};

function readCaptures(): Capture[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is Capture =>
      typeof item?.id === "string" && typeof item?.text === "string" &&
      item.text.length <= 500 && typeof item?.created_at === "string"
    ).slice(0, 20);
  } catch { return []; }
}

function App() {
  const [section, setSection] = useState<Section>("Agora");
  const [captures, setCaptures] = useState<Capture[]>(readCaptures);
  const [text, setText] = useState("");
  const [syntheticConfirmed, setSyntheticConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const [runtime, setRuntime] = useState<RuntimeEnvelope | null>(null);
  const [transport, setTransport] = useState<TransportSnapshot | null>(null);
  const [runtimeError, setRuntimeError] = useState("");
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const runtimeAvailable = isTauri();

  useEffect(() => {
    if (section !== "Runtime local" || !runtimeAvailable) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const [response, transportResponse] = await Promise.all([
          invoke<string>("runtime_status"),
          invoke<string>("runtime_transport_status"),
        ]);
        const next = parseRuntimeEnvelope(response);
        const nextTransport = parseTransportSnapshot(transportResponse);
        if (!cancelled) {
          setRuntime(next);
          setTransport(nextTransport);
          setRuntimeError("");
        }
      } catch {
        if (!cancelled) setRuntimeError("Não foi possível consultar o supervisor local.");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 350);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [section, runtimeAvailable]);

  async function runRuntimeCommand(command: RuntimeCommand) {
    setRuntimeBusy(true);
    setRuntimeError("");
    try {
      const { operation, current } = await executeRuntimeCommand(command, invoke<string>);
      setRuntime(current);
      if (!operation.ok) setRuntimeError(operation.error ?? "A ação não foi concluída.");
    } catch {
      setRuntimeError("Não foi possível chamar o supervisor local.");
    } finally {
      setRuntimeBusy(false);
    }
  }

  async function probeRuntimeTransport() {
    setRuntimeBusy(true);
    setRuntimeError("");
    try {
      setTransport(parseTransportSnapshot(await invoke<string>("runtime_transport_probe")));
    } catch {
      setRuntimeError("Não foi possível validar o canal local supervisionado.");
    } finally {
      setRuntimeBusy(false);
    }
  }

  function saveCapture(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = text.trim();
    if (!syntheticConfirmed || !content || content.length > 500) return;
    const next = [{ id: crypto.randomUUID(), text: content, created_at: new Date().toISOString() }, ...captures].slice(0, 20);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      setCaptures(next); setText(""); setSyntheticConfirmed(false);
      setNotice("Captura fictícia salva somente neste aplicativo. Nenhuma Missão foi criada na API.");
    } catch { setNotice("Não foi possível salvar localmente. O texto continua no campo para recuperação."); }
  }

  function clearCaptures() {
    try { localStorage.removeItem(STORAGE_KEY); setCaptures([]); setNotice("Capturas fictícias deste aplicativo removidas."); }
    catch { setNotice("Não foi possível remover as capturas locais."); }
  }

  return <div className="shell">
    <aside className="rail">
      <div className="brand" aria-label="JARVIS"><span className="mark">JV</span><span>JARVIS</span></div>
      <nav aria-label="Seções do JARVIS">{sections.map((item) => <button
        aria-current={section === item ? "page" : undefined} className={section === item ? "nav-item active" : "nav-item"}
        key={item} onClick={() => { setSection(item); setNotice(""); }} type="button">{item}</button>)}</nav>
      <p className="rail-note">macOS local · dados fictícios · sem conexão externa</p>
    </aside>
    <main className="content" id="conteudo">
      <p className="eyebrow">VICTOR OS · CLIENTE MACOS · {section === "Runtime local" ? "VALIDAÇÃO LOCAL" : "DEMO OFFLINE"}</p>
      <h1>{section}</h1>
      {notice && <p className="notice" role="status">{notice}</p>}
      {section === "Agora" && <article className="card"><p className="badge">DEMO LOCAL</p>
        <h2>Clareza antes de automação.</h2>
        <p>Este aplicativo abre sem conta ou servidor. Há {captures.length} captura(s) fictícia(s) neste Mac. Nenhuma fonte pessoal foi lida.</p>
        <button className="action" type="button" onClick={() => setSection("Inbox")}>Capturar uma ideia de teste</button>
      </article>}
      {section === "Inbox" && <article className="card"><p className="badge">SOMENTE TEXTO FICTÍCIO</p>
        <h2>Captura local com confirmação</h2>
        <p>Escreva apenas conteúdo de teste. Ele ficará neste aplicativo e não será enviado à API.</p>
        <form onSubmit={saveCapture}><label htmlFor="desktop-capture">Ideia de teste</label>
          <textarea id="desktop-capture" maxLength={500} value={text} onChange={(event) => setText(event.currentTarget.value)} placeholder="Ex.: preparar um resumo sintético" />
          <label className="confirm"><input type="checkbox" checked={syntheticConfirmed} onChange={(event) => setSyntheticConfirmed(event.currentTarget.checked)} /> Confirmo que o texto é fictício e pode ser salvo neste Mac.</label>
          <button className="action" type="submit" disabled={!text.trim() || !syntheticConfirmed}>Salvar captura fictícia</button>
        </form>
        <h3>Capturas neste aplicativo ({captures.length})</h3>
        {captures.length === 0 ? <p>Nenhuma captura local.</p> : <ul className="capture-list">{captures.map((item) => <li key={item.id}><span>{item.text}</span><small>{new Date(item.created_at).toLocaleString("pt-BR")}</small></li>)}</ul>}
      </article>}
      {section === "Missões" && <article className="card"><p className="badge">API NÃO CONECTADA</p>
        <h2>Execução permanece na web local</h2>
        <p>Esta edição macOS não cria nem executa Missões no servidor. As {captures.length} captura(s) fictícia(s) estão somente neste aplicativo. Para a jornada sintética com SQLite e revisão, abra a web local e entre na integração.</p>
        <ol><li><span>Capturar no Mac</span><span>{captures.length} local(is)</span></li><li><span>Criar Missão na API</span><span>Não conectado</span></li><li><span>Revisar artefato</span><span>Na web local</span></li></ol>
      </article>}
      {section === "Aprovações" && <article className="card"><p className="badge">SEM CONCESSÃO ATIVA</p>
        <h2>Nenhuma decisão neste cliente</h2><p>A fila persistente depende de sessão, concessão e API local. Este aplicativo não simula decisões nem aprova conteúdo automaticamente.</p>
      </article>}
      {section === "Runtime local" && <article className="card runtime-card">
        <p className="badge">RUNTIME DE TESTE</p>
        <h2>Processo local supervisionado</h2>
        <p>Este helper sintético valida início, prontidão, encerramento e recuperação. Ele não acessa a API G5, SQLite, rede ou dados do produto.</p>
        <dl className="runtime-status" aria-live="polite">
          <div><dt>Estado</dt><dd>{runtime ? runtimeStateLabels[runtime.snapshot.state] : runtimeAvailable ? "Consultando" : "Indisponível neste preview"}</dd></div>
          <div><dt>Canal autenticado</dt><dd>{transport ? transportStateLabels[transport.state] : runtimeAvailable ? "Consultando" : "Indisponível neste preview"}</dd></div>
          {transport?.state === "READY" && <div><dt>Transporte</dt><dd>Socket Unix · protocolo {transport.protocol_version}</dd></div>}
          {transport?.error_category && <div><dt>Falha do canal</dt><dd>{transport.error_category}</dd></div>}
          {runtime?.snapshot.pid !== null && runtime?.snapshot.pid !== undefined && <div><dt>PID informativo</dt><dd>{runtime.snapshot.pid}</dd></div>}
          {runtime?.snapshot.runtime_instance_id && <div><dt>Instância</dt><dd><code>{runtime.snapshot.runtime_instance_id}</code></dd></div>}
          {runtime?.snapshot.failure_category && <div><dt>Categoria</dt><dd>{runtime.snapshot.failure_category}</dd></div>}
          {runtime?.snapshot.exit_code !== null && runtime?.snapshot.exit_code !== undefined && <div><dt>Código de saída</dt><dd>{runtime.snapshot.exit_code}</dd></div>}
        </dl>
        <div className="runtime-actions">
          <button className="action" type="button" disabled={!runtimeAvailable || runtimeBusy || runtime?.snapshot.state !== "STOPPED"} onClick={() => void runRuntimeCommand("runtime_start_test")}>Iniciar</button>
          <button className="action secondary" type="button" disabled={!runtimeAvailable || runtimeBusy || !["STARTING", "READY", "STOPPING"].includes(runtime?.snapshot.state ?? "")} onClick={() => void runRuntimeCommand("runtime_stop")}>Parar</button>
          <button className="action secondary" type="button" disabled={!runtimeAvailable || runtimeBusy || !["FAILED", "CRASHED"].includes(runtime?.snapshot.state ?? "")} onClick={() => void runRuntimeCommand("runtime_restart_test")}>Reiniciar</button>
          <button className="action secondary" type="button" disabled={!runtimeAvailable || runtimeBusy || runtime?.snapshot.state !== "READY" || transport?.state === "READY"} onClick={() => void probeRuntimeTransport()}>Verificar canal local</button>
        </div>
        {!runtimeAvailable && <p className="runtime-hint">Os comandos de processo ficam disponíveis somente no aplicativo macOS. Este preview web não inicia processos.</p>}
        {runtimeError && <p className="notice" role="alert">{runtimeError}</p>}
      </article>}
      {section === "Configurações" && <article className="card"><p className="badge">PRIVACIDADE LOCAL</p>
        <h2>Estado deste aplicativo</h2><p>Modo DEMO offline. Sem OAuth, sincronização, serviço em segundo plano ou conexão com dados pessoais. As capturas fictícias ficam no armazenamento local da WebView.</p>
        <button className="action secondary" type="button" disabled={captures.length === 0} onClick={clearCaptures}>Apagar capturas fictícias</button>
      </article>}
    </main>
  </div>;
}

export default App;
