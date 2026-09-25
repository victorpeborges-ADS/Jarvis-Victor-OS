import type { Artifact, Mission, MissionCheckpoint, MissionEvent, MissionTask } from "@/lib/mission-contracts";
import { buildContextSkill, captureAndClassify, draftEvidencedReport } from "@/lib/skill-catalog";

export type IdFactory = (prefix: string) => string;

function randomId(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return `${prefix}_${suffix}`;
}

function event(
  mission: Mission,
  idFactory: IdFactory,
  now: string,
  type: MissionEvent["type"],
  message: string,
  taskId: string | null,
  idempotencyKey: string
): MissionEvent {
  return { id: idFactory("event"), type, message, task_id: taskId, created_at: now, idempotency_key: `${mission.id}:${idempotencyKey}` };
}

function checkpoint(idFactory: IdFactory, now: string, taskId: string | null, state: MissionCheckpoint["state"], note: string): MissionCheckpoint {
  return { id: idFactory("checkpoint"), task_id: taskId, state, note, created_at: now };
}

export function createMission(
  title: string,
  domainId: string | null,
  options: { id?: string; now?: string; idFactory?: IdFactory } = {}
): Mission {
  const idFactory = options.idFactory ?? randomId;
  const now = options.now ?? new Date().toISOString();
  const id = options.id ?? idFactory("mission");
  const tasks: MissionTask[] = [
    { id: "task_capture", title: "Capturar e classificar entradas sintéticas", status: "planned", depends_on: [], attempt: 1, idempotency_key: `${id}:capture:1`, updated_at: now, failure_reason: null },
    { id: "task_context", title: "Montar contexto autorizado", status: "planned", depends_on: ["task_capture"], attempt: 1, idempotency_key: `${id}:context:1`, updated_at: now, failure_reason: null },
    { id: "task_report", title: "Gerar rascunho com evidências", status: "planned", depends_on: ["task_context"], attempt: 1, idempotency_key: `${id}:report:1`, updated_at: now, failure_reason: null }
  ];
  const mission: Mission = {
    schema_version: 1,
    id,
    title: title.trim().slice(0, 240),
    description: "Fluxo local de demonstração com dados 100% sintéticos.",
    status: "planned",
    domain_id: domainId,
    tasks,
    checkpoints: [checkpoint(idFactory, now, null, "created", "Missão criada em armazenamento local do navegador.")],
    events: [],
    artifacts: [],
    budget: { cap: 0, spent: 0 },
    created_at: now,
    updated_at: now
  };
  mission.events.push(event(mission, idFactory, now, "mission_created", "Missão sintética criada.", null, "created"));
  return mission;
}

export function runNextStep(mission: Mission, options: { now?: string; idFactory?: IdFactory; idempotencyKey?: string } = {}): Mission {
  if (["cancelled", "failed", "done"].includes(mission.status)) return mission;
  const now = options.now ?? new Date().toISOString();
  const idFactory = options.idFactory ?? randomId;
  const task = mission.tasks.find((candidate) =>
    ["planned", "blocked"].includes(candidate.status) && candidate.depends_on.every((id) => mission.tasks.some((dependency) => dependency.id === id && dependency.status === "done"))
  );
  if (!task) {
    const hasOpenTasks = mission.tasks.some((candidate) => !["done", "cancelled"].includes(candidate.status));
    return hasOpenTasks ? { ...mission, status: "blocked", updated_at: now } : { ...mission, status: "done", updated_at: now };
  }

  const runKey = `run:${task.id}:${task.attempt}`;
  const requestKey = options.idempotencyKey ?? runKey;
  if (mission.events.some((item) => item.idempotency_key === `${mission.id}:request:${requestKey}`)) return mission;
  if (mission.events.some((item) => item.idempotency_key === `${mission.id}:${runKey}:completed`)) return mission;
  const updatedTasks = mission.tasks.map((candidate) => candidate.id === task.id ? { ...candidate, status: "done" as const, updated_at: now, failure_reason: null } : candidate);
  const events = [
    ...mission.events,
    event(mission, idFactory, now, "task_started", `Início simulado: ${task.title}.`, task.id, `request:${requestKey}`),
    event(mission, idFactory, now, "task_completed", `Concluída por regra determinística: ${task.title}.`, task.id, `${runKey}:completed`)
  ];
  const checkpoints = [
    ...mission.checkpoints,
    checkpoint(idFactory, now, task.id, "started", "Execução simulada local; sem chamada externa."),
    checkpoint(idFactory, now, task.id, "completed", "Etapa concluída sem efeitos externos.")
  ];
  let artifacts: Artifact[] = mission.artifacts;
  const sourceId = `synthetic:mission:${mission.id}`;
  const source = { source_id: sourceId, uri: null, observed_at: now, last_verified_at: now, valid_until: null, domain_id: mission.domain_id };
  let created: Artifact | null = null;
  if (task.id === "task_capture") {
    const knowledge = captureAndClassify(`Captura fictícia para a missão ${mission.title}.`, mission.domain_id, now, `${mission.id}_capture`);
    created = { id: idFactory("artifact"), kind: "evidence", title: "Captura classificada (simulada)", content: `Tipo: ${knowledge.kind} · estado: ${knowledge.state} · escopo: ${knowledge.domain_id ?? "não classificado"}. ${knowledge.content}`, skill_version: "1.0.0", source_refs: [source], created_at: now };
  } else if (task.id === "task_context") {
    const built = buildContextSkill([{ ...source, content: `Contexto fictício autorizado para ${mission.title}.` }], {
      task_id: task.id, mission_id: mission.id, allowed_source_ids: new Set([sourceId]),
      allowed_domains: new Set(mission.domain_id ? [mission.domain_id] : []), domain_id: mission.domain_id,
      now, max_bytes: 2048
    });
    created = { id: idFactory("artifact"), kind: "context_bundle", title: "Pacote de contexto sintético", content: `${built.text || "Nenhuma fonte autorizada foi incluída."}\n\nIncluídos: ${built.bundle.included.length} · omitidos: ${built.bundle.omitted.length} · ${built.bundle.size_bytes}/${built.bundle.budget_bytes} bytes. ${built.bundle.omitted.map((item) => `${item.source_id} (${item.reason})`).join("; ")}`.trim(), skill_version: "1.0.0", source_refs: built.bundle.included, created_at: now };
  } else if (task.id === "task_report") {
    const refs = mission.artifacts.find((artifact) => artifact.kind === "context_bundle")?.source_refs ?? [source];
    const completedMission = { ...mission, tasks: updatedTasks };
    created = draftEvidencedReport(completedMission, refs, now, idFactory("draft"));
  }
  if (created) {
    artifacts = [...artifacts, created];
    events.push(event(mission, idFactory, now, "artifact_created", `${created.title} criado pela skill sintética v1.0.0.`, task.id, `${runKey}:artifact`));
  }
  const complete = updatedTasks.every((candidate) => candidate.status === "done");
  return { ...mission, tasks: updatedTasks, events, checkpoints, artifacts, status: complete ? "done" : "running", updated_at: now };
}

export function failMissionTask(mission: Mission, taskId: string, reason: string, options: { now?: string; idFactory?: IdFactory } = {}): Mission {
  const task = mission.tasks.find((candidate) => candidate.id === taskId);
  if (!task || ["done", "cancelled"].includes(task.status)) return mission;
  const now = options.now ?? new Date().toISOString();
  const idFactory = options.idFactory ?? randomId;
  const key = `${mission.id}:fail:${task.id}:${task.attempt}`;
  if (mission.events.some((item) => item.idempotency_key === key)) return mission;
  return {
    ...mission,
    status: "failed",
    tasks: mission.tasks.map((candidate) => candidate.id === taskId ? { ...candidate, status: "failed" as const, failure_reason: reason.slice(0, 500), updated_at: now } : candidate),
    events: [...mission.events, event(mission, idFactory, now, "task_failed", reason.slice(0, 1000), taskId, `fail:${task.id}:${task.attempt}`)],
    checkpoints: [...mission.checkpoints, checkpoint(idFactory, now, taskId, "failed", reason.slice(0, 1000))],
    updated_at: now
  };
}

export function retryMissionTask(mission: Mission, taskId: string, options: { now?: string; idFactory?: IdFactory } = {}): Mission {
  const task = mission.tasks.find((candidate) => candidate.id === taskId);
  if (!task || task.status !== "failed") return mission;
  const now = options.now ?? new Date().toISOString();
  const idFactory = options.idFactory ?? randomId;
  const attempt = task.attempt + 1;
  return {
    ...mission,
    status: "planned",
    tasks: mission.tasks.map((candidate) => candidate.id === taskId ? { ...candidate, status: "planned" as const, attempt, idempotency_key: `${mission.id}:${taskId}:${attempt}`, failure_reason: null, updated_at: now } : candidate),
    events: [...mission.events, event(mission, idFactory, now, "task_retried", `Nova tentativa ${attempt} preparada.`, taskId, `retry:${taskId}:${attempt}`)],
    checkpoints: [...mission.checkpoints, checkpoint(idFactory, now, taskId, "created", `Tentativa ${attempt} criada; sem efeitos externos anteriores.`)],
    updated_at: now
  };
}

export function cancelMission(mission: Mission, options: { now?: string; idFactory?: IdFactory } = {}): Mission {
  if (["cancelled", "done"].includes(mission.status)) return mission;
  const now = options.now ?? new Date().toISOString();
  const idFactory = options.idFactory ?? randomId;
  return {
    ...mission,
    status: "cancelled",
    tasks: mission.tasks.map((task) => ["done", "failed", "cancelled"].includes(task.status) ? task : { ...task, status: "cancelled", updated_at: now }),
    events: [...mission.events, event(mission, idFactory, now, "mission_cancelled", "Missão cancelada localmente pelo usuário.", null, "cancelled")],
    checkpoints: [...mission.checkpoints, checkpoint(idFactory, now, null, "cancelled", "Missão cancelada; nenhuma operação externa pendente.")],
    updated_at: now
  };
}
