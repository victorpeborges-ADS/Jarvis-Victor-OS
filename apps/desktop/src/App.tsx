import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import "./App.css";
import { createG5Ipc, executeRuntimeCommand, grantIsDisplayedActive, parseLocalRuntimeConfig, parseRuntimeEnvelope, parseTransportSnapshot } from "./runtimeCommand";
import type { ConnectorStatus, G5CommandResult, G5Mission, G5PendingReview, G5ReviewDetail, G5SessionSnapshot, LocalAutomation, LocalAutomationRun, LocalCapture, LocalRuntimeConfig, RuntimeEnvelope, RuntimeState, RuntimeCommand, TransportSnapshot, TransportState, WorkflowState, WorkflowTask, WorkflowTaskSummary } from "./runtimeCommand";

const g5Ipc = createG5Ipc((command, args) => invoke<string>(command, args));
const sections = ["Agora", "Inbox", "Missões", "Aprovações", "Automações", "Runtime local", "Configurações"] as const;
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

const workflowStateLabels: Record<WorkflowState, string> = {
  proposed: "Proposta", awaiting_approval: "Aguardando confirmação", paused: "Pausada",
  running: "Em execução", interrupted: "Interrompida", succeeded: "Concluída",
  failed: "Falhou", cancelled: "Cancelada",
};

const automationKindLabels: Record<LocalAutomation["kind"], string> = {
  reminder: "Lembrete",
  morning_briefing: "Briefing da manhã",
  idea_mission_review: "Revisão de ideias e missões",
};

const runStatusLabels: Record<LocalAutomationRun["status"], string> = {
  running: "Em execução", deferred: "Aguardando horário permitido", retry_wait: "Nova tentativa agendada",
  succeeded: "Concluída", failed: "Falhou", missed: "Perdida", pending: "Aguardando",
  superseded: "Substituída por mudança no agendamento",
};

function localDateTimeInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes());
}

function formatAutomationTime(value: string, timezone: string): string {
  try {
    return new Date(value).toLocaleString("pt-BR", { timeZone: timezone });
  } catch {
    return "fuso horário inválido";
  }
}

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
  const [grantConfirmed, setGrantConfirmed] = useState(false);
  const [missions, setMissions] = useState<G5Mission[]>([]);
  const [connectors, setConnectors] = useState<ConnectorStatus | null>(null);
  const [localConfig, setLocalConfig] = useState<LocalRuntimeConfig | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [draftConfirmed, setDraftConfirmed] = useState(false);
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [automations, setAutomations] = useState<LocalAutomation[]>([]);
  const [automationRuns, setAutomationRuns] = useState<LocalAutomationRun[]>([]);
  const [automationSelected, setAutomationSelected] = useState("");
  const [automationDetailData, setAutomationDetailData] = useState<LocalAutomation | null>(null);
  const [automationRunDetail, setAutomationRunDetail] = useState<LocalAutomationRun | null>(null);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [automationError, setAutomationError] = useState("");
  const [automationKind, setAutomationKind] = useState<LocalAutomation["kind"]>("reminder");
  const [automationTitle, setAutomationTitle] = useState("");
  const [automationRecurrence, setAutomationRecurrence] = useState<LocalAutomation["recurrence"]>("daily");
  const [automationSchedule, setAutomationSchedule] = useState("09:00");
  const [automationTimezone, setAutomationTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [automationMessage, setAutomationMessage] = useState("");
  const [quietStart, setQuietStart] = useState("");
  const [quietEnd, setQuietEnd] = useState("");
  const [localSourcesConfirmed, setLocalSourcesConfirmed] = useState(false);
  const seenAutomationRuns = useRef(new Set<string>());
  const initializedAutomationNotice = useRef(false);
  const [reviewGrant, setReviewGrant] = useState(false);
  const [pendingReviews, setPendingReviews] = useState<G5PendingReview[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [reviewDetail, setReviewDetail] = useState<G5ReviewDetail | null>(null);
  const [workflowTasks, setWorkflowTasks] = useState<WorkflowTaskSummary[]>([]);
  const [workflowDetail, setWorkflowDetail] = useState<WorkflowTask | null>(null);
  const [workflowTitle, setWorkflowTitle] = useState("");
  const [workflowBody, setWorkflowBody] = useState("");
  const [simulationSubject, setSimulationSubject] = useState("");
  const [simulationBody, setSimulationBody] = useState("");
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
            setWorkflowTasks([]);
            setWorkflowDetail(null);
            setPendingReviews([]);
            setReviewDetail(null);
            setApprovalConfirmed(false);
            setDraftConfirmed(false);
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
        const [listed, status, workflows] = await Promise.all([g5Ipc.listCaptures(), g5Ipc.connectorStatus(), g5Ipc.workflowList()]);
        if (cancelled) return;
        if (listed.ok) {
          setCaptures(listed.captures ?? []);
          setG5Error("");
        } else {
          setCaptures([]);
          setG5Error(listed.error ?? "O banco local não está disponível; as ideias não foram atualizadas.");
        }
        setConnectors(status);
        setWorkflowTasks(workflows.ok ? workflows.tasks ?? [] : []);
      } catch {
        if (!cancelled) {
          setConnectors(null);
          setCaptures([]);
          setWorkflowTasks([]);
          setG5Error("Não foi possível ler o banco local autenticado.");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [runtimeAvailable, g5Status?.session_active, section]);

  useEffect(() => {
    if (!runtimeAvailable || !g5Status?.session_active || section !== "Automações") {
      setAutomations([]);
      setAutomationRuns([]);
      setAutomationDetailData(null);
      setAutomationRunDetail(null);
      return;
    }
    let cancelled = false;
    const refreshAutomations = async () => {
      try {
        const result = await g5Ipc.automationsList();
        if (!cancelled && result.ok) {
          const items = result.automations ?? [];
          setAutomations(items);
          setAutomationSelected((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? "");
          setAutomationError("");
        } else if (!cancelled) {
          setAutomationError(result.error ?? "Não foi possível consultar as automações locais.");
        }
      } catch {
        if (!cancelled) setAutomationError("O canal local não respondeu ao consultar as automações.");
      }
    };
    void refreshAutomations();
    const timer = window.setInterval(() => void refreshAutomations(), 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [runtimeAvailable, g5Status?.session_active, section]);

  useEffect(() => {
    if (!runtimeAvailable || !g5Status?.session_active || !automationSelected || section !== "Automações") return;
    let cancelled = false;
    void Promise.all([
      g5Ipc.automationHistory(automationSelected),
      g5Ipc.automationDetail(automationSelected),
    ]).then(([history, detail]) => {
      if (cancelled) return;
      if (history.ok) setAutomationRuns(history.runs ?? []);
      else setAutomationError(history.error ?? "O histórico não pôde ser lido.");
      if (detail.ok && detail.automation) setAutomationDetailData(detail.automation);
      else setAutomationError(detail.error ?? "Os detalhes do agendamento não puderam ser lidos.");
    }).catch(() => { if (!cancelled) setAutomationError("Não foi possível ler os detalhes locais."); });
    return () => { cancelled = true; };
  }, [runtimeAvailable, g5Status?.session_active, automationSelected, section, automations]);

  useEffect(() => {
    if (!runtimeAvailable || !g5Status?.session_active ||
        runtime?.snapshot.state !== "READY" || transport?.state !== "READY") return;
    let cancelled = false;
    const pollFinishedRuns = async () => {
      try {
        const listed = await g5Ipc.automationsList();
        if (!listed.ok || cancelled) return;
        const recent = await Promise.all((listed.automations ?? []).filter((automation) => automation.state !== "deleted").map(async (automation) => ({
          automation,
          history: await g5Ipc.automationHistory(automation.id),
        })));
        if (cancelled) return;
        if (!initializedAutomationNotice.current) {
          for (const item of recent) for (const run of item.history.runs ?? []) seenAutomationRuns.current.add(run.id);
          initializedAutomationNotice.current = true;
          const missed = recent.find((item) => (item.history.runs ?? []).some((run) => run.status === "missed"));
          if (missed && !cancelled) setNotice(missed.automation.title + ": há uma execução perdida. Abra Automações para revisar e decidir se deseja recuperar.");
          return;
        }
        for (const item of recent) {
          if (!item.history.ok) continue;
          const fresh = (item.history.runs ?? []).filter((run) => !seenAutomationRuns.current.has(run.id));
          for (const run of fresh) seenAutomationRuns.current.add(run.id);
          const finished = fresh.find((run) => ["succeeded", "failed", "missed"].includes(run.status));
          if (!finished || cancelled) continue;
          if (finished.status === "succeeded") {
            const detail = await g5Ipc.automationRun(item.automation.id, finished.id);
            if (!cancelled) setNotice(detail.ok && detail.run?.output
              ? item.automation.title + ": " + detail.run.output
              : item.automation.title + ": rascunho local pronto; confira o histórico de Automações.");
          } else if (!cancelled) {
            setNotice(item.automation.title + ": " + runStatusLabels[finished.status] + ". Confira Automações.");
          }
        }
      } catch {
        // The automation screen presents channel failures; never log schedule content.
      }
    };
    void pollFinishedRuns();
    const timer = window.setInterval(() => void pollFinishedRuns(), 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [runtimeAvailable, g5Status?.session_active, runtime?.snapshot.state, transport?.state]);

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

  async function runG5Command(action: "open-session" | "create-grant" | "revoke-grant" | "close-session" | "list-missions") {
    setG5Busy(true);
    setG5Error("");
    if (action === "create-grant") setGrantConfirmed(false);
    try {
      let result: G5CommandResult;
      switch (action) {
        case "open-session":
          result = await g5Ipc.openSession();
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
        if (action === "close-session") {
          setReviewGrant(false);
          setPendingReviews([]);
          setReviewDetail(null);
          setApprovalConfirmed(false);
          setReviewConfirmed(false);
        }
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
        if (listed.ok) {
          setCaptures(listed.captures ?? []);
        } else {
          setCaptures([]);
          setG5Error(listed.error ?? "O banco local não está disponível; as ideias não foram atualizadas.");
        }
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

  async function saveCapture(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = text.trim();
    if (!content || [...content].length > 80) return;
    setG5Busy(true);
    setG5Error("");
    try {
      const saved = editingId
        ? await g5Ipc.editCapture(editingId, content)
        : await g5Ipc.createCapture(content);
      if (!saved.ok) {
        setG5Error(saved.error ?? "A captura não foi gravada.");
        return;
      }
      const listed = await g5Ipc.listCaptures();
      if (!listed.ok) {
        setCaptures([]);
        setText("");
        setEditingId(null);
        setNotice("A ideia foi gravada, mas a lista local não pôde ser atualizada.");
        setG5Error(listed.error ?? "Banco local indisponível; confira a lista antes de gravar outra ideia.");
        return;
      }
      setCaptures(listed.captures ?? []);
      setText("");
      setEditingId(null);
      setNotice(editingId
        ? "Ideia atualizada no banco local. Nada foi enviado para fora."
        : "Ideia gravada no banco local sintético. Nenhuma missão, e-mail ou evento foi criado.");
    } catch {
      setG5Error("Não foi possível gravar a ideia no banco local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function removeCapture(captureId: string) {
    setG5Busy(true);
    setG5Error("");
    try {
      const removed = await g5Ipc.deleteCapture(captureId);
      if (!removed.ok) {
        setG5Error(removed.error ?? "A ideia não foi apagada.");
        return;
      }
      const listed = await g5Ipc.listCaptures();
      if (listed.ok) {
        setCaptures(listed.captures ?? []);
      } else {
        setCaptures((current) => current.filter((item) => item.id !== captureId));
        setG5Error(listed.error ?? "A ideia foi apagada, mas a lista local não pôde ser atualizada.");
      }
      if (editingId === captureId) {
        setEditingId(null);
        setText("");
      }
      setNotice("Ideia apagada do banco local. Nada foi enviado para fora.");
    } catch {
      setG5Error("Não foi possível apagar a ideia.");
    } finally {
      setG5Busy(false);
    }
  }

  async function requestReviewGrant() {
    setG5Busy(true);
    setG5Error("");
    setReviewConfirmed(false);
    setReviewDetail(null);
    setApprovalConfirmed(false);
    setDraftConfirmed(false);
    setPendingReviews([]);
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

  async function revokeReviewGrant() {
    setG5Busy(true);
    setG5Error("");
    try {
      const result = await g5Ipc.revokeReviewGrant();
      if (!result.ok || !result.review_grant_revoked) throw new Error(result.error ?? "A concessão de revisão não foi revogada.");
      setReviewGrant(false);
      setWorkflowDetail(null);
      setNotice("Concessão mission:review revogada. Tarefas pendentes não podem executar sem novo consentimento.");
    } catch (error) {
      setG5Error(error instanceof Error ? error.message : "Não foi possível revogar a concessão de revisão.");
    } finally {
      setG5Busy(false);
    }
  }

  async function queueReviewDraft() {
    if (!draftConfirmed) return;
    setG5Busy(true);
    setG5Error("");
    try {
      const queued = await g5Ipc.queueReviewDraft();
      if (!queued.ok) {
        setG5Error(queued.error ?? "O rascunho local não foi criado.");
        return;
      }
      const pending = await g5Ipc.pendingReviews();
      setPendingReviews(pending.ok ? pending.reviews ?? [] : []);
      setDraftConfirmed(false);
      setNotice(queued.queued ? "Rascunho sintético colocado na fila. Nada foi enviado para fora." : "Já existe uma revisão pendente. Nenhuma nova foi criada.");
    } catch {
      setG5Error("Não foi possível criar o rascunho local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function loadReviewDetail(review: G5PendingReview) {
    setG5Busy(true);
    setG5Error("");
    setReviewDetail(null);
    setApprovalConfirmed(false);
    try {
      const result = await g5Ipc.reviewDetail(review);
      if (!result.ok || !result.review_detail) {
        setG5Error(result.error ?? "O conteúdo integral da revisão não está disponível para conferência.");
        return;
      }
      setReviewDetail(result.review_detail);
    } catch {
      setG5Error("Não foi possível carregar o conteúdo integral da revisão local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function approveReview() {
    if (!reviewDetail || !approvalConfirmed) return;
    setG5Busy(true);
    setG5Error("");
    try {
      const result = await g5Ipc.approveReview(reviewDetail);
      if (!result.ok || !result.approved) {
        setG5Error(result.error ?? "A aprovação local foi recusada; atualize a revisão antes de tentar novamente.");
        return;
      }
      setReviewDetail(null);
      setApprovalConfirmed(false);
      const pending = await g5Ipc.pendingReviews();
      if (!pending.ok) {
        setG5Error(pending.error ?? "A decisão foi registrada, mas a fila não pôde ser atualizada.");
        return;
      }
      setPendingReviews(pending.reviews ?? []);
      setNotice("Revisão aprovada no backend G5 local. Nenhuma ação externa foi executada.");
    } catch {
      setG5Error("Não foi possível concluir a decisão G5 local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function refreshWorkflowTasks() {
    const listed = await g5Ipc.workflowList();
    if (!listed.ok) throw new Error(listed.error ?? "Não foi possível listar as tarefas locais.");
    setWorkflowTasks(listed.tasks ?? []);
  }

  async function submitDraftWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setG5Busy(true);
    setG5Error("");
    try {
      const submitted = await g5Ipc.workflowSubmitDraft(workflowTitle.trim(), workflowBody.trim());
      if (!submitted.ok) throw new Error(submitted.error ?? "O rascunho foi recusado.");
      setWorkflowTitle("");
      setWorkflowBody("");
      setNotice("Tarefa de rascunho persistida localmente; nenhum serviço externo foi chamado.");
      await refreshWorkflowTasks();
    } catch (error) {
      setG5Error(error instanceof Error ? error.message : "Não foi possível criar a tarefa local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function submitSimulationWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reviewGrant) return;
    setG5Busy(true);
    setG5Error("");
    try {
      const submitted = await g5Ipc.workflowSubmitSimulation(simulationSubject.trim(), simulationBody.trim());
      if (!submitted.ok) throw new Error(submitted.error ?? "A simulação foi recusada.");
      setSimulationSubject("");
      setSimulationBody("");
      setWorkflowDetail(submitted.task ?? null);
      setNotice("Proposta de simulação persistida. Confira o payload; nada será enviado.");
      await refreshWorkflowTasks();
    } catch (error) {
      setG5Error(error instanceof Error ? error.message : "Não foi possível criar a simulação local.");
    } finally {
      setG5Busy(false);
    }
  }

  async function inspectWorkflow(taskId: string) {
    setG5Busy(true);
    setG5Error("");
    try {
      const detail = await g5Ipc.workflowDetail(taskId);
      if (!detail.ok || !detail.task) throw new Error(detail.error ?? "A tarefa não pôde ser aberta.");
      setWorkflowDetail(detail.task);
    } catch (error) {
      setG5Error(error instanceof Error ? error.message : "A tarefa local não pôde ser aberta.");
    } finally {
      setG5Busy(false);
    }
  }

  async function runWorkflowAction(action: "execute-draft" | "execute-simulation" | "pause" | "resume" | "cancel", taskId: string) {
    setG5Busy(true);
    setG5Error("");
    try {
      const result = action === "execute-draft" ? await g5Ipc.workflowExecuteDraft(taskId)
        : action === "execute-simulation" ? await g5Ipc.workflowExecuteSimulation(taskId)
          : action === "pause" ? await g5Ipc.workflowPause(taskId)
            : action === "resume" ? await g5Ipc.workflowResume(taskId)
              : await g5Ipc.workflowCancel(taskId);
      if (!result.ok) throw new Error(result.error ?? "A transição da tarefa foi recusada.");
      setWorkflowDetail(result.task ?? null);
      setNotice(action === "execute-simulation" ? "Simulação local concluída sem envio de dados." : "Estado da tarefa local atualizado.");
      await refreshWorkflowTasks();
    } catch (error) {
      setG5Error(error instanceof Error ? error.message : "Não foi possível atualizar a tarefa local.");
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

  async function refreshAutomationData(automationId = automationSelected) {
    const listed = await g5Ipc.automationsList();
    if (!listed.ok) throw new Error(listed.error ?? "Não foi possível atualizar as automações.");
    const items = listed.automations ?? [];
    setAutomations(items);
    const selected = items.some((item) => item.id === automationId) ? automationId : items[0]?.id ?? "";
    setAutomationSelected(selected);
    if (selected) {
      const history = await g5Ipc.automationHistory(selected);
      if (!history.ok) throw new Error(history.error ?? "Não foi possível atualizar o histórico.");
      setAutomationRuns(history.runs ?? []);
    } else {
      setAutomationRuns([]);
      setAutomationDetailData(null);
      setAutomationRunDetail(null);
    }
  }

  async function createAutomation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAutomationBusy(true);
    setAutomationError("");
    try {
      const created = await g5Ipc.automationCreate({
        kind: automationKind,
        title: automationTitle.trim(),
        recurrence: automationRecurrence,
        localSchedule: automationSchedule,
        timezone: automationTimezone,
        quietStart,
        quietEnd,
        message: automationKind === "reminder" ? automationMessage.trim() : "",
        confirmLocalSources: automationKind !== "reminder" && localSourcesConfirmed,
      });
      if (!created.ok || !created.id) {
        setAutomationError(created.error ?? "A automação não foi salva.");
        return;
      }
      setAutomationTitle("");
      setAutomationMessage("");
      setLocalSourcesConfirmed(false);
      await refreshAutomationData(created.id);
      setNotice("Agendamento salvo localmente. Ele só será avaliado enquanto o app estiver ativo.");
    } catch (error) {
      setAutomationError(error instanceof Error ? error.message : "Não foi possível salvar o agendamento.");
    } finally {
      setAutomationBusy(false);
    }
  }

  async function controlAutomation(automationId: string, action: "pause" | "resume" | "delete" | "recover" | "retry", runId = "") {
    setAutomationBusy(true);
    setAutomationError("");
    setAutomationRunDetail(null);
    try {
      const result = await g5Ipc.automationControl(automationId, action, runId);
      if (!result.ok) {
        setAutomationError(result.error ?? "A operação não foi concluída.");
        return;
      }
      await refreshAutomationData(automationId);
      setNotice(action === "recover" ? "Recuperação autorizada; resultado registrado no histórico local."
        : action === "retry" ? "Nova tentativa autorizada; resultado registrado no histórico local."
          : action === "delete" ? "Agendamento removido da fila; o histórico foi preservado."
            : action === "pause" ? "Agendamento pausado." : "Agendamento retomado.");
    } catch (error) {
      setAutomationError(error instanceof Error ? error.message : "O canal local não respondeu.");
    } finally {
      setAutomationBusy(false);
    }
  }

  async function changeAutomationTimezone(automationId: string) {
    setAutomationBusy(true);
    setAutomationError("");
    try {
      const result = await g5Ipc.automationTimezone(automationId, automationTimezone);
      if (!result.ok) {
        setAutomationError(result.error ?? "O fuso não foi atualizado.");
        return;
      }
      await refreshAutomationData(automationId);
      setNotice("Fuso horário atualizado; a próxima execução foi recalculada.");
    } catch (error) {
      setAutomationError(error instanceof Error ? error.message : "Não foi possível atualizar o fuso.");
    } finally {
      setAutomationBusy(false);
    }
  }

  async function showAutomationRun(automationId: string, runId: string) {
    setAutomationBusy(true);
    setAutomationError("");
    try {
      const result = await g5Ipc.automationRun(automationId, runId);
      if (!result.ok || !result.run) {
        setAutomationError(result.error ?? "O resultado não pôde ser lido.");
        return;
      }
      setAutomationRunDetail(result.run);
    } catch {
      setAutomationError("Não foi possível abrir o resultado local.");
    } finally {
      setAutomationBusy(false);
    }
  }

  return <div className="shell">
    <aside className="rail">
      <div className="brand" aria-label="JARVIS"><span className="mark">JV</span><span>JARVIS</span></div>
      <nav aria-label="Seções do JARVIS">{sections.map((item) => <button
        aria-current={section === item ? "page" : undefined} className={section === item ? "nav-item active" : "nav-item"}
        key={item} onClick={() => { setSection(item); setNotice(""); if (item !== "Missões") { setGrantConfirmed(false); } }} type="button">{item}</button>)}</nav>
      <p className="rail-note">macOS local · banco sintético · sem conta externa</p>
    </aside>
    <main className="content" id="conteudo">
      <p className="eyebrow">VICTOR OS · CLIENTE MACOS · {runtime?.snapshot.state === "READY" && transport?.state === "READY" ? "RUNTIME LOCAL" : "RUNTIME PARADO"}</p>
      <h1>{section}</h1>
      {notice && <p className="notice" role="status">{notice}</p>}
      {section === "Agora" && <article className="card"><p className="badge">BANCO LOCAL SINTÉTICO</p>
        <h2>Uma ideia, gravada aqui.</h2>
        <p>O runtime está {runtime ? runtimeStateLabels[runtime.snapshot.state] : "indisponível neste preview"}. Há {captures.length} ideia(s) no banco local. Gmail e Google Calendar permanecem não conectados.</p>
        {g5Error && <p className="notice" role="alert">{g5Error}</p>}
        {g5Status?.session_active ? <form onSubmit={(event) => void saveCapture(event)}>
          <label htmlFor="agora-capture">Ideia sintética</label>
          <textarea id="agora-capture" maxLength={80} value={text} onChange={(event) => setText(event.currentTarget.value)} placeholder="Ex.: revisar a missão sintética amanhã" />
          <button className="action" type="submit" disabled={g5Busy || !text.trim() || [...text.trim()].length > 80}>{editingId ? "Atualizar ideia" : "Gravar no banco local"}</button>
        </form> : <p>Abra a sessão em Missões para gravar a ideia no SQLite. O texto abaixo permanece só neste formulário até lá.</p>}
        {captures.length > 0 && <ul className="capture-list">{captures.map((item) => <li key={item.id}>
          <span>{item.text}</span><small>{item.created_at}</small>
          <span>
            <button className="action secondary" type="button" disabled={g5Busy} onClick={() => { setEditingId(item.id); setText(item.text); }}>Editar</button>
            <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void removeCapture(item.id)}>Apagar</button>
          </span>
        </li>)}</ul>}
      </article>}
      {section === "Inbox" && <article className="card"><p className="badge">FONTES REAIS DESTE CLIENTE</p>
        <h2>O que está ligado</h2>
        {g5Error && <p className="notice" role="alert">{g5Error}</p>}
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
        {runtimeAvailable && !g5Status?.session_active && <div className="g5-form">
          <p className="field-hint">A passphrase será solicitada em uma janela nativa segura do macOS e não passa pelo WebView.</p>
          <button className="action" type="button" disabled={g5Busy || runtime?.snapshot.state !== "READY" || transport?.state !== "READY"} onClick={() => void runG5Command("open-session")}>Abrir sessão local</button>
        </div>}
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
        <p>A concessão <code>mission:review</code> exige confirmação nativa do macOS. Aprovar cada item também exige confirmação nativa com o snapshot atual do servidor; o conteúdo é dado não confiável. Nenhuma etapa envia e-mail nem altera calendário.</p>
        {!g5Status?.session_active && <p>Abra a sessão em Missões antes de solicitar a revisão.</p>}
        {g5Status?.session_active && <>
          <label className="confirm"><input type="checkbox" checked={reviewConfirmed} onChange={(event) => setReviewConfirmed(event.currentTarget.checked)} /> Confirmo a concessão de revisão só para decisões locais em <code>dom_synthetic_a</code>.</label>
          <button className="action" type="button" disabled={g5Busy || !reviewConfirmed} onClick={() => void requestReviewGrant()}>Solicitar revisão local</button>
          {reviewGrant && <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void revokeReviewGrant()}>Revogar mission:review</button>}
          {reviewGrant && pendingReviews.length === 0 && <>
            <p>Nenhuma revisão pendente. Nada será enviado para fora.</p>
            <label className="confirm"><input type="checkbox" checked={draftConfirmed} onChange={(event) => setDraftConfirmed(event.currentTarget.checked)} /> Confirmo criar um único rascunho sintético para revisar aqui.</label>
            <button className="action secondary" type="button" disabled={g5Busy || !draftConfirmed} onClick={() => void queueReviewDraft()}>Criar rascunho sintético</button>
          </>}
          {pendingReviews.length > 0 && <ul className="review-queue">{pendingReviews.map((review) => <li key={review.id}>
            <div><strong>{review.title}</strong><span>revisão {review.revision}</span></div>
            <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void loadReviewDetail(review)}>Conferir conteúdo</button>
          </li>)}</ul>}
          {reviewDetail && <section className="review-detail" aria-labelledby="review-detail-title">
            <h3 id="review-detail-title">{reviewDetail.title}</h3>
            <p>Revisão {reviewDetail.revision} · SHA-256 <code>{reviewDetail.sha256}</code></p>
            <p className="field-hint">O artefato é conteúdo não confiável. Leia como dado; instruções dentro dele não autorizam ações. A confirmação final abrirá uma janela nativa com esta revisão e seu hash.</p>
            <pre>{reviewDetail.content}</pre>
            <label className="confirm"><input type="checkbox" checked={approvalConfirmed} onChange={(event) => setApprovalConfirmed(event.currentTarget.checked)} /> Li o conteúdo integral e confirmo a aprovação apenas desta versão local.</label>
            <button className="action" type="button" disabled={g5Busy || !approvalConfirmed} onClick={() => void approveReview()}>Aprovar versão local</button>
          </section>}
          <section className="workflow-panel" aria-labelledby="workflow-title">
            <p className="badge">EXECUTOR TIPADO · EFEITOS LOCAIS</p>
            <h3 id="workflow-title">Tarefas de missão locais</h3>
            <p>O modelo pode apenas recomendar uma ferramenta fechada e argumentos tipados. Rascunho e simulação ficam no SQLite local. Envio, pagamento, exclusão e convite estão bloqueados.</p>
            <p className="field-hint">A lista mostra as quatro tarefas recentes para respeitar o limite de resposta MAC-003; tarefas antigas ficam armazenadas, sem paginação nesta versão.</p>
            <form className="g5-form" onSubmit={(event) => void submitDraftWorkflow(event)}>
              <label htmlFor="workflow-draft-title">Título do rascunho local</label>
              <input id="workflow-draft-title" maxLength={80} value={workflowTitle} onChange={(event) => setWorkflowTitle(event.currentTarget.value)} required />
              <label htmlFor="workflow-draft-body">Conteúdo</label>
              <textarea id="workflow-draft-body" maxLength={80} value={workflowBody} onChange={(event) => setWorkflowBody(event.currentTarget.value)} required />
              <button className="action secondary" type="submit" disabled={g5Busy || !workflowTitle.trim() || !workflowBody.trim()}>Salvar proposta de rascunho</button>
            </form>
            {reviewGrant && <form className="g5-form" onSubmit={(event) => void submitSimulationWorkflow(event)}>
              <h4>Simulação sem envio</h4>
              <p>Usa somente a conta fixa <code>operator@example.test</code> e a caixa sintética local.</p>
              <label htmlFor="workflow-sim-subject">Assunto simulado</label>
              <input id="workflow-sim-subject" maxLength={30} value={simulationSubject} onChange={(event) => setSimulationSubject(event.currentTarget.value)} required />
              <label htmlFor="workflow-sim-body">Payload completo</label>
              <textarea id="workflow-sim-body" maxLength={80} value={simulationBody} onChange={(event) => setSimulationBody(event.currentTarget.value)} required />
              <button className="action secondary" type="submit" disabled={g5Busy || !simulationSubject.trim() || !simulationBody.trim()}>Preparar simulação</button>
            </form>}
            {workflowTasks.length === 0 ? <p>Nenhuma tarefa persistida nesta sessão.</p> : <ul className="workflow-list">{workflowTasks.map((task) => <li key={task.task_id}>
              <div><strong>{task.tool_id === "draft_note" ? "Rascunho local" : "Simulação local"}</strong><span>{workflowStateLabels[task.state]} · {task.risk} · {task.expected_effect}</span></div>
              {task.tool_id === "draft_note" && task.state === "proposed" && <button className="action" type="button" disabled={g5Busy} onClick={() => void runWorkflowAction("execute-draft", task.task_id)}>Executar localmente</button>}
              {task.tool_id === "simulate_action" && ["awaiting_approval", "interrupted"].includes(task.state) && <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void inspectWorkflow(task.task_id)}>Conferir payload</button>}
              {task.state === "succeeded" && <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void inspectWorkflow(task.task_id)}>Ver resultado verificável</button>}
              {task.state === "paused" && <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runWorkflowAction("resume", task.task_id)}>Retomar</button>}
              {["proposed", "awaiting_approval"].includes(task.state) && <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runWorkflowAction("pause", task.task_id)}>Pausar</button>}
              {["proposed", "awaiting_approval", "paused", "interrupted", "failed"].includes(task.state) && <button className="action secondary" type="button" disabled={g5Busy} onClick={() => void runWorkflowAction("cancel", task.task_id)}>Cancelar</button>}
            </li>)}</ul>}
            {workflowDetail && <section className="review-detail" aria-label="Detalhe da tarefa local">
              <h4>Detalhe da tarefa · {workflowStateLabels[workflowDetail.state]}</h4>
              <p>Hash dos parâmetros: <code>{workflowDetail.arguments_sha}</code></p>
              {workflowDetail.preview && <>
                <p><strong>{workflowDetail.preview.service}</strong> · conta {workflowDetail.preview.account} · alvo {workflowDetail.preview.target}</p>
                <p>Payload completo:</p><pre>{JSON.stringify(workflowDetail.preview.payload, null, 2)}</pre>
                <p>{workflowDetail.preview.consequence}</p>
                <p>Dados enviados: nenhum. Efeito esperado: {workflowDetail.expected_effect}.</p>
                {["awaiting_approval", "interrupted"].includes(workflowDetail.state) && <button className="action" type="button" disabled={g5Busy || !reviewGrant} onClick={() => void runWorkflowAction("execute-simulation", workflowDetail.task_id)}>Confirmar na janela nativa e simular</button>}
              </>}
              {workflowDetail.result && <>
                <p>Resultado local:</p><pre>{JSON.stringify(workflowDetail.result, null, 2)}</pre>
                {workflowDetail.result_sha && <p>Hash SHA-256 do resultado: <code>{workflowDetail.result_sha}</code></p>}
              </>}
            </section>}
          </section>
        </>}
      </article>}
      {section === "Automações" && <article className="card automation-page">
        <p className="badge">LOCAL · SEM SERVIÇO EM SEGUNDO PLANO</p>
        <h2>Agendamentos locais</h2>
        <p>Lembretes, briefing e revisão viram uma notificação/rascunho dentro do histórico do app. O worker existe apenas enquanto o runtime supervisionado está ativo. Não envia e-mail, cria evento nem altera dados externos.</p>
        <p>Se o Mac/app estiver desligado na hora, o histórico registra “perdida”; nada é recuperado automaticamente. A recuperação pede confirmação explícita. Horários usam o fuso IANA informado; em horário repetido pelo DST usamos a primeira ocorrência, e em horário inexistente avançamos até o primeiro minuto válido.</p>
        {!runtimeAvailable && <p className="runtime-hint">Esta função só está disponível na janela Tauri, com o runtime local ativo.</p>}
        {runtimeAvailable && !g5Status?.session_active && <p>Abra uma sessão local em Missões para administrar os agendamentos. A sessão não concede leitura por si só.</p>}
        {runtimeAvailable && g5Status?.session_active && <>
          <form className="automation-form" onSubmit={(event) => void createAutomation(event)}>
            <h3>Novo agendamento</h3>
            <label htmlFor="automation-kind">Workflow</label>
            <select id="automation-kind" value={automationKind} onChange={(event) => setAutomationKind(event.currentTarget.value as LocalAutomation["kind"])}>
              <option value="reminder">Lembrete</option>
              <option value="morning_briefing">Briefing da manhã</option>
              <option value="idea_mission_review">Revisão de ideias e missões</option>
            </select>
            <label htmlFor="automation-title">Nome</label>
            <input id="automation-title" maxLength={48} value={automationTitle} onChange={(event) => setAutomationTitle(event.currentTarget.value)} />
            <p className="field-hint">Até 24 caracteres no nome e 32 no texto; o limite mantém a chamada G5 dentro do frame local atual.</p>
            <label htmlFor="automation-recurrence">Frequência</label>
            <select id="automation-recurrence" value={automationRecurrence} onChange={(event) => {
              const recurrence = event.currentTarget.value as LocalAutomation["recurrence"];
              setAutomationRecurrence(recurrence);
              setAutomationSchedule(recurrence === "daily" ? "09:00" : localDateTimeInput(new Date(Date.now() + 60 * 60 * 1000)));
            }}>
              <option value="daily">Diária</option>
              <option value="once">Uma vez</option>
            </select>
            <label htmlFor="automation-schedule">{automationRecurrence === "daily" ? "Horário local" : "Data e hora local"}</label>
            <input id="automation-schedule" type={automationRecurrence === "daily" ? "time" : "datetime-local"} value={automationSchedule} onChange={(event) => setAutomationSchedule(event.currentTarget.value)} required />
            <label htmlFor="automation-timezone">Fuso horário IANA</label>
            <input id="automation-timezone" maxLength={64} value={automationTimezone} onChange={(event) => setAutomationTimezone(event.currentTarget.value)} required />
            <p className="field-hint">Fuso detectado: {Intl.DateTimeFormat().resolvedOptions().timeZone || "não identificado"}. A próxima execução é recalculada quando o fuso é alterado.</p>
            {automationKind === "reminder" && <>
              <label htmlFor="automation-message">Lembrete</label>
              <textarea id="automation-message" maxLength={64} value={automationMessage} onChange={(event) => setAutomationMessage(event.currentTarget.value)} required />
            </>}
            {automationKind !== "reminder" && <>
              <p className="field-hint">Usa apenas capturas locais e missões em dom_synthetic_a. Não acessa rede nem modelo.</p>
              <label className="confirm"><input type="checkbox" checked={localSourcesConfirmed} onChange={(event) => setLocalSourcesConfirmed(event.currentTarget.checked)} disabled={!grantActive} />Confirmo um briefing usando somente ideias e missões locais; requer grant mission:read ativo.</label>
            </>}
            <fieldset className="automation-quiet">
              <legend>Quiet hours (opcional)</legend>
              <label htmlFor="quiet-start">Início</label><input id="quiet-start" type="time" value={quietStart} onChange={(event) => setQuietStart(event.currentTarget.value)} />
              <label htmlFor="quiet-end">Fim</label><input id="quiet-end" type="time" value={quietEnd} onChange={(event) => setQuietEnd(event.currentTarget.value)} />
              <small>Preencha os dois horários ou deixe ambos vazios.</small>
            </fieldset>
            <button className="action" type="submit" disabled={automationBusy || automations.filter((item) => item.state !== "deleted").length >= 3 ||
              !automationTitle.trim() || [...automationTitle].length > 24 || !automationSchedule ||
              (automationKind === "reminder" && (!automationMessage.trim() || [...automationMessage].length > 32)) ||
              (automationKind !== "reminder" && (!localSourcesConfirmed || !grantActive)) || (!!quietStart !== !!quietEnd)}>
              Salvar agendamento
            </button>
          </form>
          {automationError && <p className="notice" role="alert">{automationError}</p>}
          <h3>Agendamentos ativos e recentes ({automations.filter((item) => item.state !== "deleted").length}/3)</h3>
          {automations.length === 0
            ? <p>Nenhum agendamento local ainda.</p>
            : <label htmlFor="automation-selected">Escolha um agendamento</label>}
          {automations.length > 0 && <select id="automation-selected" value={automationSelected} onChange={(event) => {
            const id = event.currentTarget.value;
            setAutomationSelected(id);
            setAutomationDetailData(null);
            const selected = automations.find((item) => item.id === id);
            if (selected) setAutomationTimezone(selected.timezone);
            setAutomationRunDetail(null);
          }}>
            {automations.map((item) => <option value={item.id} key={item.id}>{item.title} · {automationKindLabels[item.kind]}{item.state === "deleted" ? " · removido" : ""}</option>)}
          </select>}
          {automations.filter((item) => item.id === automationSelected).map((item) => <section className="automation-card" key={item.id}>
            <h3>{item.title}</h3>
            <p>{automationKindLabels[item.kind]} · {item.recurrence === "daily" ? "diária às " + item.local_schedule : "uma vez em " + item.local_schedule} · {item.timezone}</p>
            <p><strong>Estado:</strong> {item.state} · <strong>Workflow:</strong> {item.workflow_version}</p>
            <p><strong>Próxima execução:</strong> {item.next_run_at ? formatAutomationTime(item.next_run_at, item.timezone) : "nenhuma"} ({item.timezone})</p>
            <p><strong>Origem:</strong> {item.sources.join(", ")}{item.quiet_start && " · quiet hours " + item.quiet_start + "–" + item.quiet_end}</p>
            {(automationDetailData?.id === item.id ? automationDetailData.message : item.message) &&
              <p><strong>Rascunho:</strong> {automationDetailData?.id === item.id ? automationDetailData.message : item.message}</p>}
            {item.state !== "deleted" && item.state !== "completed" && <>
              <label htmlFor={"automation-timezone-" + item.id}>Alterar fuso</label>
              <div className="automation-actions">
                <input id={"automation-timezone-" + item.id} maxLength={64} value={automationTimezone} onChange={(event) => setAutomationTimezone(event.currentTarget.value)} />
                <button className="action secondary" type="button" disabled={automationBusy || !automationTimezone.trim()} onClick={() => void changeAutomationTimezone(item.id)}>Atualizar fuso</button>
              {item.state === "active" && <button className="action secondary" type="button" disabled={automationBusy} onClick={() => void controlAutomation(item.id, "pause")}>Pausar</button>}
              {item.state === "paused" && <button className="action secondary" type="button" disabled={automationBusy} onClick={() => void controlAutomation(item.id, "resume")}>Retomar</button>}
              <button className="action secondary" type="button" disabled={automationBusy} onClick={() => {
                if (window.confirm("Remover este agendamento? O histórico será preservado.")) void controlAutomation(item.id, "delete");
              }}>Apagar</button>
              </div>
            </>}
          </section>)}
          <h3>Histórico recente</h3>
          {automationRuns.length === 0 ? <p>Nenhuma execução registrada.</p> : <ul className="automation-history">{automationRuns.map((run) => {
            const selected = automations.find((item) => item.id === automationSelected);
            const needsGrant = selected?.kind !== "reminder" && !grantActive;
            return <li key={run.id}>
              <div>
                <strong>{runStatusLabels[run.status]}</strong>
                <span>{formatAutomationTime(run.scheduled_for, selected?.timezone || automationTimezone)}</span>
                <small>{run.workflow_version} · tentativas {run.attempts}/3 · origem: {run.sources.join(", ") || "nenhuma"}</small>
                {run.error_code && <small>Falha: {run.error_code}</small>}
              </div>
              <div className="automation-actions">
                <button className="action secondary" type="button" disabled={automationBusy} onClick={() => void showAutomationRun(automationSelected, run.id)}>Abrir resultado</button>
                {run.status === "missed" && <button className="action" type="button" disabled={automationBusy || needsGrant || run.attempts >= 3} onClick={() => {
                  if (window.confirm("Esta execução foi perdida. Deseja recuperar agora? Ela só usará os dados locais aprovados.")) void controlAutomation(automationSelected, "recover", run.id);
                }}>Recuperar…</button>}
                {run.status === "failed" && run.attempts < 3 && <button className="action secondary" type="button" disabled={automationBusy || needsGrant} onClick={() => {
                  if (window.confirm("Deseja fazer uma tentativa manual adicional?")) void controlAutomation(automationSelected, "retry", run.id);
                }}>Tentar novamente…</button>}
                {run.status === "failed" && run.attempts >= 3 && <small>Limite de três tentativas atingido.</small>}
              </div>
            </li>;
          })}</ul>}
          {automationRunDetail && <section className="review-detail" aria-live="polite">
            <h3>Resultado da execução</h3>
            <p>{runStatusLabels[automationRunDetail.status]} · {automationRunDetail.workflow_version} · fontes: {automationRunDetail.sources.join(", ") || "nenhuma"}</p>
            {automationRunDetail.error_code && <p role="alert">Falha: {automationRunDetail.error_code}</p>}
            {automationRunDetail.output && <pre>{automationRunDetail.output}</pre>}
          </section>}
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
