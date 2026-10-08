import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import "./App.css";
import { createG5Ipc, executeRuntimeCommand, parseRuntimeEnvelope, parseTransportSnapshot } from "./runtimeCommand";
import type { G5CommandResult, G5Mission, G5SessionSnapshot, RuntimeEnvelope, RuntimeState, RuntimeCommand, TransportSnapshot, TransportState } from "./runtimeCommand";

const STORAGE_KEY = "jarvis-desktop-demo-captures-v1";
const g5Ipc = createG5Ipc((command, args) => invoke<string>(command, args));
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

const missionStatusLabels: Record<G5Mission["status"], string> = {
  draft: "Rascunho", planned: "Planejada", awaiting_approval: "Aguardando aprovação",
  running: "Em execução", blocked: "Bloqueada", done: "Concluída", cancelled: "Cancelada",
  failed: "Falhou", interrupted: "Interrompida",
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
  const [g5Status, setG5Status] = useState<G5SessionSnapshot | null>(null);
  const [g5Busy, setG5Busy] = useState(false);
  const [g5Error, setG5Error] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [grantConfirmed, setGrantConfirmed] = useState(false);
  const [missions, setMissions] = useState<G5Mission[]>([]);
  const runtimeAvailable = isTauri();

  useEffect(() => {
    if (!(section === "Runtime local" || section === "Missões") || !runtimeAvailable) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const [response, transportResponse, g5Response] = await Promise.all([
          invoke<string>("runtime_status"),
          invoke<string>("runtime_transport_status"),
          g5Ipc.sessionStatus(),
        ]);
        const next = parseRuntimeEnvelope(response);
        const nextTransport = parseTransportSnapshot(transportResponse);
          if (!cancelled) {
            setRuntime(next);
            setTransport(nextTransport);
            setG5Status(g5Response);
            if (next.snapshot.state !== "READY" || nextTransport.state !== "READY" || !g5Response.session_active) {
              setGrantConfirmed(false);
              setMissions([]);
            } else if (!g5Response.grant_active) {
              setMissions([]);
            }
            setRuntimeError("");
        }
      } catch {
        if (!cancelled) setRuntimeError("Não foi possível consultar o supervisor local.");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 500);
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

  async function runG5Command(action: "open-session", passphrase: string): Promise<void>;
  async function runG5Command(action: "create-grant" | "revoke-grant" | "close-session" | "list-missions"): Promise<void>;
  async function runG5Command(
    action: "open-session" | "create-grant" | "revoke-grant" | "close-session" | "list-missions",
    passphrase?: string,
  ) {
    setG5Busy(true);
    setG5Error("");
    if (action === "create-grant") setGrantConfirmed(false);
    try {
      let result: G5CommandResult;
      switch (action) {
        case "open-session":
          result = await g5Ipc.openSession(passphrase ?? "");
          break;
        case "create-grant":
          result = await g5Ipc.createMissionReadGrant();
          break;
        case "revoke-grant":
          result = await g5Ipc.revokeMissionReadGrant();
          break;
        case "close-session":
          result = await g5Ipc.closeSession();
          break;
        case "list-missions":
          result = await g5Ipc.listMissions();
          break;
      }
      if (!result.ok) {
        setG5Error(result.error ?? "A operação G5 local foi recusada.");
      } else if (action === "list-missions") {
        setMissions(result.items ?? []);
      } else if (action === "revoke-grant" || action === "close-session") {
        setMissions([]);
      }
      const status = await g5Ipc.sessionStatus();
      setG5Status(status);
      if (!status.session_active || !status.grant_active) {
        setMissions([]);
        setGrantConfirmed(false);
      }
    } catch {
      setG5Error("Não foi possível falar com o backend local autenticado.");
    } finally {
      setG5Busy(false);
    }
  }

  async function openG5Session(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = passphrase;
    setPassphrase("");
    await runG5Command("open-session", value);
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
        key={item} onClick={() => { setSection(item); setNotice(""); if (item !== "Missões") { setPassphrase(""); setGrantConfirmed(false); } }} type="button">{item}</button>)}</nav>
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
      {section === "Missões" && <article className="card g5-card">
        <p className="badge">{runtime?.snapshot.state === "READY" && transport?.state === "READY" ? "FASTAPI AUTENTICADA · DADOS SINTÉTICOS" : "BACKEND LOCAL NÃO PRONTO"}</p>
        <h2>Leitura autorizada de Missões</h2>
        <p>O backend local atende somente por UDS. Uma sessão aberta não concede leitura: confirme separadamente a concessão para <code>mission:read</code> no domínio sintético <code>dom_synthetic_a</code>.</p>
        {!runtimeAvailable && <p className="runtime-hint">Este preview web não inicia processos locais nem abre sessões G5.</p>}
        {runtimeAvailable && !g5Status?.session_active && <form className="g5-form" onSubmit={(event) => void openG5Session(event)}>
          <label htmlFor="g5-passphrase">Credencial local G5</label>
          <input id="g5-passphrase" type="password" autoComplete="off" maxLength={128} value={passphrase}
            onChange={(event) => setPassphrase(event.currentTarget.value)} aria-describedby="g5-passphrase-help" />
          <p id="g5-passphrase-help" className="field-hint">Usada somente para abrir a sessão local. O campo é limpo ao enviar e a credencial não fica salva.</p>
          <button className="action" type="submit" disabled={g5Busy || runtime?.snapshot.state !== "READY" || transport?.state !== "READY" || new TextEncoder().encode(passphrase).length < 12 || new TextEncoder().encode(passphrase).length > 128}>Abrir sessão local</button>
        </form>}
        {runtimeAvailable && g5Status?.session_active && <section className="g5-state" aria-live="polite">
          <p><strong>Sessão aberta.</strong> Válida até {g5Status.session_expires_at ? new Date(g5Status.session_expires_at).toLocaleString("pt-BR") : "expirar no servidor"}.</p>
          {g5Status.grant_active ? <>
            <p><strong>Concessão ativa:</strong> leitura de Missões em <code>dom_synthetic_a</code> até {g5Status.grant_expires_at ? new Date(g5Status.grant_expires_at).toLocaleString("pt-BR") : "expirar no servidor"}.</p>
            <div className="g5-actions">
              <button className="action" type="button" disabled={g5Busy} onClick={() => void runG5Command("list-missions")}>Ler uma missão sintética</button>
              <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runG5Command("revoke-grant")}>Revogar concessão</button>
            </div>
          </> : <>
            <label className="confirm"><input type="checkbox" checked={grantConfirmed} onChange={(event) => setGrantConfirmed(event.currentTarget.checked)} /> Confirmo leitura somente de Missões sintéticas em <code>dom_synthetic_a</code> por até 60 minutos.</label>
            <div className="g5-actions">
              <button className="action" type="button" disabled={g5Busy || !grantConfirmed} onClick={() => void runG5Command("create-grant")}>Conceder leitura</button>
              <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runG5Command("list-missions")}>Tentar leitura sem concessão</button>
            </div>
          </>}
          <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runG5Command("close-session")}>Encerrar sessão e invalidar concessão</button>
        </section>}
        {g5Error && <p className="notice" role="alert">{g5Error}</p>}
        {missions.length > 0 && <section className="g5-results" aria-live="polite"><h3>Resultado da API sintética</h3>
          {missions.map((mission) => <article className="mission-summary" key={mission.id}>
            <h4>{mission.title}</h4><p>{missionStatusLabels[mission.status]} · revisão {mission.revision} · {mission.domain_id}</p>
          </article>)}
        </section>}
        {runtimeAvailable && g5Status?.grant_active && missions.length === 0 && <p className="field-hint">Nenhuma missão autorizada apareceu nesta leitura. O banco de teste permanece separado e não recebe fixtures automaticamente.</p>}
      </article>}
      {section === "Aprovações" && <article className="card"><p className="badge">SEM CONCESSÃO ATIVA</p>
        <h2>Nenhuma decisão neste cliente</h2><p>A fila persistente depende de sessão, concessão e API local. Este aplicativo não simula decisões nem aprova conteúdo automaticamente.</p>
      </article>}
      {section === "Runtime local" && <article className="card runtime-card">
        <p className="badge">RUNTIME FASTAPI / G5</p>
        <h2>Processo local supervisionado</h2>
        <p>O supervisor inicia o FastAPI local diretamente. Pronto significa startup concluído e prova MAC-002 autenticada no UDS. O runtime não abre listener TCP nem conecta fontes externas.</p>
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
          <button className="action" type="button" disabled={!runtimeAvailable || runtimeBusy || runtime?.snapshot.state !== "STOPPED"} onClick={() => void runRuntimeCommand("runtime_start")}>Iniciar</button>
          <button className="action secondary" type="button" disabled={!runtimeAvailable || runtimeBusy || !["STARTING", "READY", "STOPPING"].includes(runtime?.snapshot.state ?? "")} onClick={() => void runRuntimeCommand("runtime_stop")}>Parar</button>
          <button className="action secondary" type="button" disabled={!runtimeAvailable || runtimeBusy || !["FAILED", "CRASHED"].includes(runtime?.snapshot.state ?? "")} onClick={() => void runRuntimeCommand("runtime_restart")}>Reiniciar</button>
          <button className="action secondary" type="button" disabled={!runtimeAvailable || runtimeBusy || runtime?.snapshot.state !== "READY"} onClick={() => void probeRuntimeTransport()}>Verificar canal local</button>
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
