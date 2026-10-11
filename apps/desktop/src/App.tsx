import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import "./App.css";
import { createG5Ipc, executeRuntimeCommand, grantIsDisplayedActive, parseLocalRuntimeConfig, parseRuntimeEnvelope, parseTransportSnapshot } from "./runtimeCommand";
import type { ConnectorStatus, G5CommandResult, G5Mission, G5SessionSnapshot, LocalCapture, LocalRuntimeConfig, RuntimeEnvelope, RuntimeState, RuntimeCommand, TransportSnapshot, TransportState } from "./runtimeCommand";

const g5Ipc = createG5Ipc((command, args) => invoke<string>(command, args));
const sections = ["Agora", "Inbox", "Missões", "Aprovações", "Runtime local", "Configurações"] as const;
type Section = (typeof sections)[number];

const connectorBlockLabels = {
  missing_oauth_client: "não conectada: falta o client ID OAuth",
  consent_required: "não conectada: o client ID está presente e o consentimento da conta ainda não foi dado",
} as const;

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

function App() {
  const [section, setSection] = useState<Section>("Agora");
  const [captures, setCaptures] = useState<LocalCapture[]>([]);
  const [text, setText] = useState("");
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
  const [connectors, setConnectors] = useState<ConnectorStatus | null>(null);
  const [localConfig, setLocalConfig] = useState<LocalRuntimeConfig | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [reviewGrant, setReviewGrant] = useState(false);
  const [pendingReviews, setPendingReviews] = useState<{ id: string; revision: number; sha256: string; title: string }[]>([]);
  const runtimeAvailable = isTauri();
  const grantActive = g5Status ? grantIsDisplayedActive(g5Status, nowMs) : false;

  useEffect(() => {
    if (!runtimeAvailable) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const [response, transportResponse, g5Response, configResponse] = await Promise.all([
          invoke<string>("runtime_status"),
          invoke<string>("runtime_transport_status"),
          g5Ipc.sessionStatus(),
          invoke<string>("runtime_local_config"),
        ]);
        const next = parseRuntimeEnvelope(response);
        const nextTransport = parseTransportSnapshot(transportResponse);
        if (!cancelled) {
          setRuntime(next);
          setTransport(nextTransport);
          setG5Status(g5Response);
          setLocalConfig(parseLocalRuntimeConfig(configResponse));
          setNowMs(Date.now());
          if (next.snapshot.state !== "READY" || nextTransport.state !== "READY" || !g5Response.session_active) {
            setGrantConfirmed(false);
            setMissions([]);
            setCaptures([]);
            setConnectors(null);
            setReviewGrant(false);
            setPendingReviews([]);
          } else if (!grantIsDisplayedActive(g5Response, Date.now())) {
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
  }, [runtimeAvailable]);

  useEffect(() => {
    if (!runtimeAvailable || !g5Status?.session_active) return;
    let cancelled = false;
    void (async () => {
      try {
        const [listed, status] = await Promise.all([g5Ipc.listCaptures(), g5Ipc.connectorStatus()]);
        if (cancelled) return;
        if (listed.ok) setCaptures(listed.captures ?? []);
        setConnectors(status);
      } catch {
        if (!cancelled) setConnectors(null);
      }
    })();
    return () => { cancelled = true; };
  }, [runtimeAvailable, g5Status?.session_active, section]);

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
      setNowMs(Date.now());
      if (!status.session_active || !grantIsDisplayedActive(status, Date.now())) {
        setMissions([]);
        setGrantConfirmed(false);
      }
      if (status.session_active) {
        const listed = await g5Ipc.listCaptures();
        if (listed.ok) setCaptures(listed.captures ?? []);
        setConnectors(await g5Ipc.connectorStatus());
      } else {
        setCaptures([]);
        setConnectors(null);
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

  async function saveCapture(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = text.trim();
    if (!content || [...content].length > 80) return;
    setG5Busy(true);
    setG5Error("");
    try {
      const saved = await g5Ipc.createCapture(content);
      if (!saved.ok) {
        setG5Error(saved.error ?? "A captura não foi gravada.");
        return;
      }
      const listed = await g5Ipc.listCaptures();
      if (!listed.ok) {
        setG5Error(listed.error ?? "A captura foi enviada, mas a lista não voltou.");
        return;
      }
      setCaptures(listed.captures ?? []);
      setText("");
      setNotice("Ideia gravada no banco local sintético. Nenhuma missão, e-mail ou evento foi criado.");
    } catch {
      setG5Error("Não foi possível gravar a ideia no banco local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function requestReviewGrant() {
    setG5Busy(true);
    setG5Error("");
    try {
      const granted = await g5Ipc.createReviewGrant();
      if (!granted.ok) {
        setReviewGrant(false);
        setG5Error(granted.error ?? "A concessão de revisão não foi criada.");
        return;
      }
      setReviewGrant(true);
      const pending = await g5Ipc.pendingReviews();
      if (!pending.ok) {
        setG5Error(pending.error ?? "A fila de revisão não pôde ser lida.");
        return;
      }
      setPendingReviews(pending.reviews ?? []);
      setNotice("Concessão mission:review registrada. Nenhuma ação externa foi executada.");
    } catch {
      setG5Error("Não foi possível solicitar a revisão local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function clearCaptures() {
    setG5Busy(true);
    setG5Error("");
    try {
      const cleared = await g5Ipc.clearCaptures();
      if (!cleared.ok) {
        setG5Error(cleared.error ?? "Não foi possível apagar as capturas.");
        return;
      }
      setCaptures([]);
      setNotice("Capturas locais apagadas do banco sintético.");
    } catch {
      setG5Error("Não foi possível apagar as capturas locais.");
    } finally {
      setG5Busy(false);
    }
  }

  return <div className="shell">
    <aside className="rail">
      <div className="brand" aria-label="JARVIS"><span className="mark">JV</span><span>JARVIS</span></div>
      <nav aria-label="Seções do JARVIS">{sections.map((item) => <button
        aria-current={section === item ? "page" : undefined} className={section === item ? "nav-item active" : "nav-item"}
        key={item} onClick={() => { setSection(item); setNotice(""); if (item !== "Missões") { setPassphrase(""); setGrantConfirmed(false); } }} type="button">{item}</button>)}</nav>
      <p className="rail-note">macOS local · banco sintético · sem conta externa</p>
    </aside>
    <main className="content" id="conteudo">
      <p className="eyebrow">VICTOR OS · CLIENTE MACOS · {runtime?.snapshot.state === "READY" && transport?.state === "READY" ? "RUNTIME LOCAL" : "RUNTIME PARADO"}</p>
      <h1>{section}</h1>
      {notice && <p className="notice" role="status">{notice}</p>}
      {section === "Agora" && <article className="card"><p className="badge">BANCO LOCAL SINTÉTICO</p>
        <h2>Uma ideia, gravada aqui.</h2>
        <p>O runtime está {runtime ? runtimeStateLabels[runtime.snapshot.state] : "indisponível neste preview"}. Há {captures.length} ideia(s) no banco local. Gmail e Google Calendar permanecem não conectados.</p>
        {g5Status?.session_active ? <form onSubmit={(event) => void saveCapture(event)}>
          <label htmlFor="agora-capture">Ideia sintética</label>
          <textarea id="agora-capture" maxLength={80} value={text} onChange={(event) => setText(event.currentTarget.value)} placeholder="Ex.: revisar a missão sintética amanhã" />
          <button className="action" type="submit" disabled={g5Busy || !text.trim() || [...text.trim()].length > 80}>Gravar no banco local</button>
        </form> : <p>Abra a sessão em Missões para gravar a ideia no SQLite. O texto abaixo permanece só neste formulário até lá.</p>}
        {captures.length > 0 && <ul className="capture-list">{captures.map((item) => <li key={item.id}><span>{item.text}</span><small>{item.created_at}</small></li>)}</ul>}
      </article>}
      {section === "Inbox" && <article className="card"><p className="badge">FONTES REAIS DESTE CLIENTE</p>
        <h2>O que está ligado</h2>
        <ul>
          <li><span>Runtime local</span><span>{runtime ? runtimeStateLabels[runtime.snapshot.state] : "indisponível"}</span></li>
          <li><span>Canal UDS</span><span>{transport ? transportStateLabels[transport.state] : "indisponível"}{transport?.error_category ? ` · ${transport.error_category}` : ""}</span></li>
          <li><span>Gmail somente leitura</span><span>{connectors ? connectorBlockLabels[connectors.gmail_block] : "não conectada"}</span></li>
          <li><span>Google Calendar somente leitura</span><span>{connectors ? connectorBlockLabels[connectors.calendar_block] : "não conectada"}</span></li>
          <li><span>Calendar simulado</span><span>sintético na API; não é a conta Google</span></li>
        </ul>
        {runtimeError && <p className="notice" role="alert">{runtimeError}</p>}
        <h3>Ideias gravadas ({captures.length})</h3>
        {captures.length === 0 ? <p>Nenhuma ideia no banco local. A sessão precisa estar aberta para gravar.</p> : <ul className="capture-list">{captures.map((item) => <li key={item.id}><span>{item.text}</span><small>{item.created_at}</small></li>)}</ul>}
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
          {g5Status.grant_active && grantActive ? <>
            <p><strong>Concessão ativa:</strong> leitura de Missões em <code>dom_synthetic_a</code> até {g5Status.grant_expires_at ?? "o instante informado pelo servidor"}. O relógio da tela usa o instante numérico do servidor.</p>
            <div className="g5-actions">
              <button className="action" type="button" disabled={g5Busy} onClick={() => void runG5Command("list-missions")}>Ler uma missão sintética</button>
              <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runG5Command("revoke-grant")}>Revogar concessão</button>
            </div>
          </> : <>
            {g5Status.grant_active && !grantActive && <p role="status">A concessão expirou neste relógio. O servidor é quem autoriza a próxima leitura.</p>}
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
        {runtimeAvailable && grantActive && missions.length === 0 && <p className="field-hint">Nenhuma missão autorizada apareceu nesta leitura. O banco de teste permanece separado e não recebe fixtures automaticamente.</p>}
      </article>}
      {section === "Aprovações" && <article className="card"><p className="badge">SEM EFEITO EXTERNO</p>
        <h2>Revisão local, com confirmação</h2>
        <p>A concessão <code>mission:review</code> só é pedida se você confirmar. Ela não é automática e não envia e-mail nem altera calendário.</p>
        {!g5Status?.session_active && <p>Abra a sessão em Missões antes de solicitar a revisão.</p>}
        {g5Status?.session_active && <>
          <label className="confirm"><input type="checkbox" checked={reviewConfirmed} onChange={(event) => setReviewConfirmed(event.currentTarget.checked)} /> Confirmo a concessão de revisão só para decisões locais em <code>dom_synthetic_a</code>.</label>
          <button className="action" type="button" disabled={g5Busy || !reviewConfirmed} onClick={() => void requestReviewGrant()}>Solicitar revisão local</button>
          {reviewGrant && pendingReviews.length === 0 && <p>Nenhuma revisão pendente. Nada será enviado para fora.</p>}
          {pendingReviews.length > 0 && <ul>{pendingReviews.map((review) => <li key={review.id}><span>{review.title}</span><span>revisão {review.revision}</span></li>)}</ul>}
        </>}
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
      {section === "Configurações" && <article className="card"><p className="badge">O QUE ESTE APP SUPORTA</p>
        <h2>Estado local</h2>
        <ul>
          <li><span>Passphrase no ambiente</span><span>{localConfig?.passphrase_configured ? "presente" : "ausente"}</span></li>
          <li><span>Banco</span><span>{localConfig?.database_mode === "override" ? "caminho de teste" : "estável em Application Support"}</span></li>
          <li><span>JARVIS_API_ROOT</span><span>{localConfig?.api_root_configured ? "definido" : "usa o checkout de desenvolvimento"}</span></li>
          <li><span>Client ID OAuth</span><span>{localConfig?.oauth_client_configured ? "presente, sem consentimento" : "ausente"}</span></li>
          <li><span>Gmail</span><span>{connectors ? connectorBlockLabels[connectors.gmail_block] : "não conectada"}</span></li>
          <li><span>Google Calendar</span><span>{connectors ? connectorBlockLabels[connectors.calendar_block] : "não conectada"}</span></li>
        </ul>
        <p>A passphrase não é gravada nem exibida. O launcher só a repassa se ela já estiver no ambiente. Não há Keychain, instalador nem runner embutido.</p>
        <button className="action secondary" type="button" disabled={!g5Status?.session_active || g5Busy || captures.length === 0} onClick={() => void clearCaptures()}>Apagar ideias do banco local</button>
      </article>}
    </main>
  </div>;
}

export default App;
