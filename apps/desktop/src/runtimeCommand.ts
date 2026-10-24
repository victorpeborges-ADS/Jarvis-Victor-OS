export type RuntimeState = "STOPPED" | "STARTING" | "READY" | "STOPPING" | "FAILED" | "CRASHED";

export type RuntimeSnapshot = {
  state: RuntimeState;
  runtime_instance_id: string | null;
  pid: number | null;
  started_at_unix_ms: number | null;
  ready_at_unix_ms: number | null;
  exit_code: number | null;
  failure_category: string | null;
};

export type RuntimeEnvelope = { ok: boolean; snapshot: RuntimeSnapshot; error: string | null };
export type RuntimeCommand = "runtime_start" | "runtime_stop" | "runtime_restart";
export type TransportState = "DISCONNECTED" | "DISCOVERING" | "PROVING_INSTANCE" | "READY" | "INCOMPATIBLE" | "FAILED";
export type TransportSnapshot = {
  state: TransportState;
  runtime_instance_id: string | null;
  endpoint_type: "uds" | null;
  protocol_version: string | null;
  error_category: string | null;
};

export type G5SessionSnapshot = {
  ok: true;
  session_active: boolean;
  session_expires_at: string | null;
  session_expires_at_epoch_us: number | null;
  grant_active: boolean;
  grant_domain_id: string | null;
  grant_expires_at: string | null;
  grant_expires_at_epoch_us: number | null;
};

export type LocalCapture = { id: string; text: string; created_at: string };
export type CaptureOrigin = LocalCapture & { domain_id: "dom_synthetic_a"; category: "explicit_capture" };
export type MemoryCategory = "explicit_capture" | "confirmed_fact" | "external_evidence" | "inferred_proposal";
export type MemoryDomain = "dom_synthetic_a" | "dom_synthetic_b" | "dom_synthetic_c" | "dom_synthetic_d" | "dom_synthetic_e" | "dom_synthetic_f" | "dom_synthetic_g" | "dom_synthetic_h";
export type LocalMemoryRecord = {
  id: string; category: MemoryCategory; domain_id: MemoryDomain; body: string;
  source_kind: "user_authored_capture" | "owner_confirmation" | "synthetic_source" | "assistant_inference";
  source_ref: string; version: number; recorded_at: string; revised_at: string;
};
export type GroundedReadSource = { id: string; kind: "capture" | "confirmed_fact" | "document"; domain_id: "dom_synthetic_a"; snippet: string };
export type GroundedReadResult = {
  status: "evidence" | "insufficient_basis" | "budget_exhausted" | "context_limit" | "provider_timeout" | "provider_failed" | "cancelled" | "stale_session" | "response_too_large";
  reason: string;
  provider_id: "fake-deterministic";
  cost: "unmeasured";
  text: string;
  omitted: number;
  sources: GroundedReadSource[];
};
export type SyntheticDocumentArtifact = {
  id: string;
  schema_version: 1;
  kind: "synthetic_document";
  title: "Resumo sintético de exemplo";
  sections: [{ index: 1; heading: "Conteúdo de teste"; paragraphs: ["Este documento contém somente texto sintético local."]; source_id: "src_exemplo_sintetico" }];
  origin: { skill_id: "generate-synthetic-document"; skill_version: "1.0.0"; manifest_sha256: string; license_name: "nao-declarada-no-arquivo-local" };
  permission: { capability: "generate_synthetic_document"; scope: "synthetic"; principal: "owner" };
};
// The WebView invokes only the operation name; Rust injects these credentials in this wire order.
export const STORAGE_ROTATE_WIRE_FIELDS = ["database_key", "generation", "operation_id", "intent"] as const;
export const STORAGE_ROTATE_RETIRE_WIRE_FIELDS = ["from_account"] as const;
export const STORAGE_ROTATE_FINALIZE_WIRE_FIELDS = ["database_key", "operation_id"] as const;
export const SYNTHETIC_DOCUMENT_WIRE_FIELDS = ["session_token", "csrf_token"] as const;
export const CONVERSATION_ASK_WIRE_FIELDS = ["session_token", "conversation_id", "question", "domain_id"] as const;
export const CONVERSATION_OPEN_WIRE_FIELDS = ["session_token", "domain_id", "mode"] as const;
export const CONVERSATION_CANCEL_WIRE_FIELDS = ["session_token", "conversation_id", "domain_id"] as const;
export type ConversationRequestTicket = { conversationId: string; generation: number };

export class ConversationRequestGate {
  private generation = 0;
  private activeConversation = "";

  begin(conversationId: string): ConversationRequestTicket {
    this.activeConversation = conversationId;
    this.generation += 1;
    return { conversationId, generation: this.generation };
  }

  isCurrent(ticket: ConversationRequestTicket, visibleConversationId: string): boolean {
    return ticket.generation === this.generation &&
      ticket.conversationId === this.activeConversation &&
      ticket.conversationId === visibleConversationId;
  }

  invalidate(): void {
    this.generation += 1;
    this.activeConversation = "";
  }
}
export type G5PendingReview = { id: string; revision: number; sha256: string; title: string };
export type G5ReviewDetail = G5PendingReview & { content: string };
export type WorkflowState = "proposed" | "awaiting_approval" | "paused" | "running" | "interrupted" | "succeeded" | "failed" | "cancelled";
export type WorkflowPreview = {
  service: string;
  account: string;
  target: string;
  payload: { subject: string; body: string };
  consequence: string;
  data_sent: string[];
  risk: "medium";
};
export type WorkflowTaskSummary = {
  task_id: string;
  tool_id: "draft_note" | "simulate_action";
  state: WorkflowState;
  arguments_sha: string;
  created_at: string;
  updated_at: string;
  risk: "low" | "medium";
  expected_effect: string;
};
export type WorkflowTask = WorkflowTaskSummary & {
  idempotency_key: string;
  permission: string;
  timeout_ms: number;
  limit: number;
  retry: { max_attempts: number; retryable: string[] };
  enabled: boolean;
  preview?: WorkflowPreview;
  result?: Record<string, unknown>;
  result_sha?: string;
  effect?: string;
  attempts?: number;
};

export type ConnectorStatus = {
  ok: true;
  gmail: "not_connected";
  gmail_block: "missing_oauth_client" | "consent_required";
  gmail_scope: "gmail.readonly";
  calendar: "not_connected";
  calendar_block: "missing_oauth_client" | "consent_required";
  calendar_scope: "calendar.readonly";
  calendar_sim: "synthetic_local";
};

export type LocalRuntimeConfig = {
  ok: true;
  passphrase_configured: boolean;
  database_configured: boolean;
  database_mode: "stable" | "override";
  api_root_configured: boolean;
  oauth_client_configured: boolean;
};

export type G5Mission = {
  id: string;
  title: string;
  domain_id: "dom_synthetic_a";
  status: "draft" | "planned" | "awaiting_approval" | "running" | "blocked" | "done" | "cancelled" | "failed" | "interrupted";
  revision: number;
};

export type LocalAutomation = {
  id: string;
  kind: "reminder" | "morning_briefing" | "idea_mission_review";
  title: string;
  recurrence: "once" | "daily";
  local_schedule: string;
  timezone: string;
  state: "active" | "paused" | "completed" | "deleted";
  next_run_at: string;
  workflow_version: string;
  sources: string[];
  quiet_start: string;
  quiet_end: string;
  message?: string;
};

export type LocalAutomationRun = {
  id: string;
  scheduled_for: string;
  status: "running" | "deferred" | "retry_wait" | "succeeded" | "failed" | "missed" | "pending" | "superseded";
  attempts: number;
  error_code: string;
  completed_at: string;
  workflow_version: string;
  sources: string[];
  output?: string;
};

export type G5CommandResult = {
  ok: boolean;
  error?: string;
  session_active?: boolean;
  grant_active?: boolean;
  expires_at?: string;
  domain_id?: string;
  dataset?: "api_synthetic";
  items?: G5Mission[];
  captures?: LocalCapture[];
  has_item?: boolean;
  memory_record?: LocalMemoryRecord;
  exported?: boolean;
  origin?: CaptureOrigin;
  omitted?: number;
  grounded_read?: GroundedReadResult;
  artifact?: SyntheticDocumentArtifact;
  artifact_sha256?: string;
  cancelled?: boolean;
  reviews?: G5PendingReview[];
  review_detail?: G5ReviewDetail;
  approved?: boolean;
  replayed?: boolean;
  review_grant?: boolean;
  review_grant_revoked?: boolean;
  task?: WorkflowTask;
  tasks?: WorkflowTaskSummary[];
  queued?: boolean;
  id?: string;
  created_at?: string;
  cleared?: boolean;
  deleted?: boolean;
  automations?: LocalAutomation[];
  automation?: LocalAutomation;
  runs?: LocalAutomationRun[];
  run?: LocalAutomationRun;
  timezone?: string;
  next_run_at?: string;
  state?: "active" | "paused" | "completed" | "deleted";
  workflow_version?: string;
};

type G5Invoke = (command: string, args?: Record<string, unknown>) => Promise<string>;

export function createG5Ipc(invokeG5: G5Invoke) {
  return {
    sessionStatus: async (): Promise<G5SessionSnapshot> =>
      parseG5SessionSnapshot(await invokeG5("g5_session_status")),
    openSession: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_session_open")),
    createMissionReadGrant: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_mission_read_grant_create")),
    revokeMissionReadGrant: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_mission_read_grant_revoke")),
    closeSession: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_session_close")),
    listMissions: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_missions_list")),
    createCapture: async (text: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_create", { text })),
    listCaptures: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_list")),
    searchCaptures: async (query: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_search", { query })),
    openCapture: async (captureId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_open", { capture_id: captureId })),
    groundedRead: async (conversationId: string, question: string): Promise<G5CommandResult> => {
      if (!/^[0-9a-f]{32}$/.test(conversationId) || typeof question !== "string" ||
          [...question].length < 1 || [...question].length > 400 || /[\u0000-\u001f\u007f]/.test(question)) {
        throw new Error("Pergunta local inválida.");
      }
      return parseG5CommandResult(await invokeG5("g5_conversation_ask", {
        conversation_id: conversationId,
        question,
      }));
    },
    openConversation: async (mode: "new" | "resume"): Promise<G5CommandResult> => {
      if (mode !== "new" && mode !== "resume") throw new Error("Modo de conversa inválido.");
      return parseG5CommandResult(await invokeG5("g5_conversation_open", { mode }));
    },
    cancelConversation: async (conversationId: string): Promise<G5CommandResult> => {
      if (!/^[0-9a-f]{32}$/.test(conversationId)) throw new Error("Conversa inválida.");
      return parseG5CommandResult(await invokeG5("g5_conversation_cancel", { conversation_id: conversationId }));
    },
    generateSyntheticDocument: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_synthetic_document_generate")),
    clearCaptures: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_clear")),
    editCapture: async (captureId: string, text: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_edit", { capture_id: captureId, text })),
    deleteCapture: async (captureId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_capture_delete", { capture_id: captureId })),
    memoryPage: async (category: MemoryCategory, domainId: MemoryDomain, offset: number): Promise<G5CommandResult> => {
      if (!validMemoryCategory(category) || !validMemoryDomain(domainId) || !Number.isSafeInteger(offset) || offset < 0 || offset > 5000) {
        throw new Error("Consulta de memória inválida.");
      }
      return parseG5CommandResult(await invokeG5("g5_memory_page", { category, domainId, offset }));
    },
    memoryCreate: async (category: MemoryCategory, domainId: MemoryDomain, body: string, sourceRef: string): Promise<G5CommandResult> => {
      if (!validMemoryCategory(category) || !validMemoryDomain(domainId) || !validMemoryBody(body) || !validMemorySourceRef(sourceRef)) {
        throw new Error("Item de memória inválido.");
      }
      return parseG5CommandResult(await invokeG5("g5_memory_create", { category, domainId, body, sourceRef }));
    },
    memoryEdit: async (category: MemoryCategory, domainId: MemoryDomain, recordId: string, body: string, expectedRevision: number): Promise<G5CommandResult> => {
      if (!validMemoryCategory(category) || !validMemoryDomain(domainId) || !/^[0-9a-f]{32}$/.test(recordId) ||
          !validMemoryBody(body) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || expectedRevision >= 0x7fffffff) {
        throw new Error("Correção de memória inválida.");
      }
      return parseG5CommandResult(await invokeG5("g5_memory_edit", { category, domainId, recordId, body, expectedRevision }));
    },
    memoryDelete: async (category: MemoryCategory, domainId: MemoryDomain, recordId: string, expectedRevision: number): Promise<G5CommandResult> => {
      if (!validMemoryCategory(category) || !validMemoryDomain(domainId) || !/^[0-9a-f]{32}$/.test(recordId) ||
          !Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || expectedRevision > 0x7fffffff) {
        throw new Error("Exclusão de memória inválida.");
      }
      return parseG5CommandResult(await invokeG5("g5_memory_delete", { category, domainId, recordId, expectedRevision }));
    },
    memoryExport: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_memory_export")),
    connectorStatus: async (): Promise<ConnectorStatus> =>
      parseConnectorStatus(await invokeG5("g5_connectors_status")),
    createReviewGrant: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_review_grant_create")),
    revokeReviewGrant: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_review_grant_revoke")),
    pendingReviews: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_reviews_pending")),
    queueReviewDraft: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_review_draft")),
    reviewDetail: async (review: G5PendingReview): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_review_detail", {
        reviewId: review.id,
        revision: review.revision,
        sha256: review.sha256,
      })),
    approveReview: async (review: G5ReviewDetail): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_review_approve", {
        reviewId: review.id,
        revision: review.revision,
        sha256: review.sha256,
      })),
    workflowPage: async (cursor = ""): Promise<WorkflowPageResult> => {
      if (!validWorkflowCursor(cursor)) throw new Error("Cursor de histórico inválido.");
      return parseWorkflowPageResult(await invokeG5("g5_workflow_page", { cursor }), cursor);
    },
    workflowList: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_list")),
    workflowDetail: async (taskId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_detail", { taskId })),
    workflowSubmitDraft: async (title: string, body: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_submit_draft", { title, body })),
    workflowSubmitSimulation: async (subject: string, body: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_submit_simulation", { subject, body })),
    workflowExecuteDraft: async (taskId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_execute_draft", { taskId })),
    workflowExecuteSimulation: async (taskId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_execute_simulation", { taskId })),
    workflowPause: async (taskId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_pause", { taskId })),
    workflowResume: async (taskId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_resume", { taskId })),
    workflowCancel: async (taskId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_workflow_cancel", { taskId })),
    automationsList: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_automations_list")),
    automationDetail: async (automationId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_automation_detail", { automationId })),
    automationHistory: async (automationId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_automation_history", { automationId })),
    automationRun: async (automationId: string, runId: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_automation_run", { automationId, runId })),
    automationCreate: async (input: {
      kind: LocalAutomation["kind"]; title: string; recurrence: LocalAutomation["recurrence"];
      localSchedule: string; timezone: string; quietStart: string; quietEnd: string;
      message: string; confirmLocalSources: boolean;
    }): Promise<G5CommandResult> => parseG5CommandResult(await invokeG5("g5_automation_create", input)),
    automationTimezone: async (automationId: string, timezone: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_automation_timezone", { automationId, timezone })),
    automationControl: async (automationId: string, action: "pause" | "resume" | "delete" | "recover" | "retry", runId = ""): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_automation_control", { automationId, action, runId })),
  };
}

const states: RuntimeState[] = ["STOPPED", "STARTING", "READY", "STOPPING", "FAILED", "CRASHED"];
const transportStates: TransportState[] = ["DISCONNECTED", "DISCOVERING", "PROVING_INSTANCE", "READY", "INCOMPATIBLE", "FAILED"];
const memoryCategories: MemoryCategory[] = ["explicit_capture", "confirmed_fact", "external_evidence", "inferred_proposal"];
const memoryDomains: MemoryDomain[] = ["dom_synthetic_a", "dom_synthetic_b", "dom_synthetic_c", "dom_synthetic_d", "dom_synthetic_e", "dom_synthetic_f", "dom_synthetic_g", "dom_synthetic_h"];

function validMemoryCategory(value: string): value is MemoryCategory {
  return memoryCategories.includes(value as MemoryCategory);
}

function validMemoryDomain(value: string): value is MemoryDomain {
  return memoryDomains.includes(value as MemoryDomain);
}

function validMemoryBody(value: string): boolean {
  return typeof value === "string" && [...value].length >= 1 && [...value].length <= 80 && !/[\u0000-\u001f\u007f]/.test(value);
}

function validMemorySourceRef(value: string): boolean {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
}

function parseMemoryRecord(value: unknown): LocalMemoryRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("Registro de memória inválido.");
  const record = value as Record<string, unknown>;
  const keys = ["id", "category", "domain_id", "body", "source_kind", "source_ref", "version", "recorded_at", "revised_at"];
  if (Object.keys(record).length !== keys.length || keys.some((key) => !(key in record)) ||
      typeof record.id !== "string" || !/^[0-9a-f]{32}$/.test(record.id) ||
      typeof record.category !== "string" || !validMemoryCategory(record.category) ||
      typeof record.domain_id !== "string" || !validMemoryDomain(record.domain_id) ||
      typeof record.body !== "string" || !validMemoryBody(record.body) ||
      typeof record.source_ref !== "string" || !validMemorySourceRef(record.source_ref) ||
      typeof record.version !== "number" || !Number.isSafeInteger(record.version) || record.version < 1 || record.version > 0x7fffffff ||
      typeof record.recorded_at !== "string" || !validAutomationTimestamp(record.recorded_at) ||
      typeof record.revised_at !== "string" || !validAutomationTimestamp(record.revised_at)) {
    throw new Error("Registro de memória inválido.");
  }
  const sourceKinds: Record<MemoryCategory, LocalMemoryRecord["source_kind"]> = {
    explicit_capture: "user_authored_capture", confirmed_fact: "owner_confirmation",
    external_evidence: "synthetic_source", inferred_proposal: "assistant_inference",
  };
  if (record.source_kind !== sourceKinds[record.category] ||
      (record.category === "explicit_capture" && (record.domain_id !== "dom_synthetic_a" || record.source_ref !== "explicit_capture"))) {
    throw new Error("Origem de memória inválida.");
  }
  return record as LocalMemoryRecord;
}

export function parseRuntimeEnvelope(value: string): RuntimeEnvelope {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null || !("snapshot" in parsed)) {
    throw new Error("Resposta de runtime inválida.");
  }
  const envelope = parsed as RuntimeEnvelope;
  if (typeof envelope.snapshot?.state !== "string" || !states.includes(envelope.snapshot.state)) {
    throw new Error("Estado de runtime desconhecido.");
  }
  return envelope;
}

export function parseTransportSnapshot(value: string): TransportSnapshot {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null || !("state" in parsed)) {
    throw new Error("Resposta de transporte inválida.");
  }
  const record = parsed as Record<string, unknown>;
  if (typeof record.state !== "string" || !transportStates.includes(record.state as TransportState)) {
    throw new Error("Estado de transporte desconhecido.");
  }
  if (record.endpoint_type !== null && record.endpoint_type !== "uds") {
    throw new Error("Tipo de endpoint de transporte desconhecido.");
  }
  const optionalText = (key: string): string | null => {
    const field = record[key];
    if (field !== null && typeof field !== "string") throw new Error(`Campo ${key} inválido.`);
    return field as string | null;
  };
  return {
    state: record.state as TransportState,
    runtime_instance_id: optionalText("runtime_instance_id"),
    endpoint_type: record.endpoint_type as "uds" | null,
    protocol_version: optionalText("protocol_version"),
    error_category: optionalText("error_category"),
  };
}

export function parseG5SessionSnapshot(value: string): G5SessionSnapshot {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null) throw new Error("Estado G5 inválido.");
  const record = parsed as Record<string, unknown>;
  const optionalText = (key: string): string | null => {
    const field = record[key];
    if (field !== null && typeof field !== "string") throw new Error(`Campo ${key} inválido.`);
    return field as string | null;
  };
  if (record.ok !== true || typeof record.session_active !== "boolean" || typeof record.grant_active !== "boolean") {
    throw new Error("Estado G5 inválido.");
  }
  const optionalEpoch = (key: string): number | null => {
    const field = record[key];
    if (field === undefined || field === null) return null;
    if (typeof field !== "number" || !Number.isSafeInteger(field) || field < 0) {
      throw new Error(`Campo ${key} inválido.`);
    }
    return field;
  };
  return {
    ok: true,
    session_active: record.session_active,
    session_expires_at: optionalText("session_expires_at"),
    session_expires_at_epoch_us: optionalEpoch("session_expires_at_epoch_us"),
    grant_active: record.grant_active,
    grant_domain_id: optionalText("grant_domain_id"),
    grant_expires_at: optionalText("grant_expires_at"),
    grant_expires_at_epoch_us: optionalEpoch("grant_expires_at_epoch_us"),
  };
}

export function grantIsDisplayedActive(status: G5SessionSnapshot, nowMs: number): boolean {
  if (!status.grant_active || status.grant_expires_at_epoch_us === null) return false;
  return status.grant_expires_at_epoch_us > nowMs * 1000;
}

export function parseG5CommandResult(value: string): G5CommandResult {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null || typeof (parsed as Record<string, unknown>).ok !== "boolean") {
    throw new Error("Resposta G5 inválida.");
  }
  const record = parsed as Record<string, unknown>;
  const result: G5CommandResult = { ok: record.ok as boolean };
  if (record.id !== undefined && record.expires_at !== undefined) {
    if (record.ok !== true || Object.keys(record).length !== 3 ||
        Object.keys(record).some((key) => !["ok", "id", "expires_at"].includes(key)) ||
        typeof record.id !== "string" || !/^[0-9a-f]{32}$/.test(record.id) ||
        typeof record.expires_at !== "string" || !Number.isFinite(Date.parse(record.expires_at)) ||
        Date.parse(record.expires_at) <= Date.now()) {
      throw new Error("Identidade de conversa inválida.");
    }
    return { ok: true, id: record.id, expires_at: record.expires_at };
  }
  if (record.has_item !== undefined || record.record !== undefined) {
    if (record.ok !== true) throw new Error("Resposta da lista de memória inválida.");
    if (record.has_item === false && Object.keys(record).length === 2 && !("record" in record)) {
      result.has_item = false;
    } else if (record.has_item === true && Object.keys(record).length === 3 && record.record !== undefined) {
      result.has_item = true;
      result.memory_record = parseMemoryRecord(record.record);
    } else if (record.has_item === undefined && Object.keys(record).length === 2 && record.record !== undefined) {
      result.memory_record = parseMemoryRecord(record.record);
    } else {
      throw new Error("Resposta da lista de memória inválida.");
    }
    if (result.memory_record && ((record.has_item === true) !== (result.has_item === true))) {
      throw new Error("Resposta da lista de memória inválida.");
    }
    return result;
  }
  if (record.artifact !== undefined) {
    if (record.ok !== true || Object.keys(record).length !== 3 ||
        Object.keys(record).some((key) => !["ok", "artifact", "artifact_sha256"].includes(key)) ||
        typeof record.artifact_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(record.artifact_sha256)) {
      throw new Error("Resposta do documento sintético inválida.");
    }
    const artifact = record.artifact as Record<string, unknown>;
    const artifactKeys = ["id", "schema_version", "kind", "title", "sections", "origin", "permission"];
    if (typeof artifact !== "object" || artifact === null || Array.isArray(artifact) ||
        Object.keys(artifact).length !== artifactKeys.length || artifactKeys.some((key) => !(key in artifact))) {
      throw new Error("Documento sintético inválido.");
    }
    const section = Array.isArray(artifact.sections) && artifact.sections.length === 1 ? artifact.sections[0] as Record<string, unknown> : null;
    const origin = typeof artifact.origin === "object" && artifact.origin !== null && !Array.isArray(artifact.origin)
      ? artifact.origin as Record<string, unknown> : null;
    const permission = typeof artifact.permission === "object" && artifact.permission !== null && !Array.isArray(artifact.permission)
      ? artifact.permission as Record<string, unknown> : null;
    if (typeof artifact.id !== "string" || !/^doc_[0-9a-f]{16}$/.test(artifact.id) ||
        artifact.schema_version !== 1 || artifact.kind !== "synthetic_document" ||
        artifact.title !== "Resumo sintético de exemplo" || !section ||
        Object.keys(section).length !== 4 || !["index", "heading", "paragraphs", "source_id"].every((key) => key in section) ||
        section.index !== 1 || section.heading !== "Conteúdo de teste" ||
        JSON.stringify(section.paragraphs) !== JSON.stringify(["Este documento contém somente texto sintético local."]) ||
        section.source_id !== "src_exemplo_sintetico" || !origin ||
        Object.keys(origin).length !== 4 || !["skill_id", "skill_version", "manifest_sha256", "license_name"].every((key) => key in origin) ||
        origin.skill_id !== "generate-synthetic-document" || origin.skill_version !== "1.0.0" ||
        typeof origin.manifest_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(origin.manifest_sha256) ||
        origin.license_name !== "nao-declarada-no-arquivo-local" || !permission ||
        Object.keys(permission).length !== 3 || !["capability", "scope", "principal"].every((key) => key in permission) ||
        permission.capability !== "generate_synthetic_document" || permission.scope !== "synthetic" || permission.principal !== "owner") {
      throw new Error("Documento sintético inválido.");
    }
    result.artifact = artifact as SyntheticDocumentArtifact;
    result.artifact_sha256 = record.artifact_sha256;
  }
  if (record.grounded_read !== undefined) {
    if (record.ok !== true || Object.keys(record).length !== 2 ||
        Object.keys(record).some((key) => !["ok", "grounded_read"].includes(key)) ||
        typeof record.grounded_read !== "object" || record.grounded_read === null || Array.isArray(record.grounded_read)) {
      throw new Error("Resposta de conversa local inválida.");
    }
    const read = record.grounded_read as Record<string, unknown>;
    const expected = ["status", "reason", "provider_id", "cost", "text", "omitted", "sources"];
    if (Object.keys(read).length !== expected.length || expected.some((key) => !(key in read)) ||
        Object.keys(read).some((key) => !expected.includes(key))) {
      throw new Error("Resposta de conversa local inválida.");
    }
    const statuses = ["evidence", "insufficient_basis", "budget_exhausted", "context_limit", "provider_timeout", "provider_failed", "cancelled", "stale_session", "response_too_large"];
    if (typeof read.status !== "string" || !statuses.includes(read.status) ||
        typeof read.reason !== "string" || !/^[a-z_]{0,32}$/.test(read.reason) ||
        read.provider_id !== "fake-deterministic" || read.cost !== "unmeasured" ||
        typeof read.text !== "string" || read.text.length > 1800 ||
        typeof read.omitted !== "number" || !Number.isSafeInteger(read.omitted) || read.omitted < 0 ||
        !Array.isArray(read.sources) || read.sources.length > 3) {
      throw new Error("Resposta de conversa local inválida.");
    }
    const sources = read.sources.map((item): GroundedReadSource => {
      if (typeof item !== "object" || item === null || Array.isArray(item)) throw new Error("Fonte local inválida.");
      const source = item as Record<string, unknown>;
      const keys = ["id", "kind", "domain_id", "snippet"];
      if (Object.keys(source).length !== keys.length || keys.some((key) => !(key in source)) ||
          typeof source.id !== "string" || !/^[a-z0-9_-]{1,32}$/.test(source.id) ||
          (source.kind !== "capture" && source.kind !== "confirmed_fact" && source.kind !== "document") || source.domain_id !== "dom_synthetic_a" ||
          typeof source.snippet !== "string" || source.snippet.length < 1 || [...source.snippet].length > 4096 ||
          /[\u0000-\u001f\u007f]/.test(source.snippet)) {
        throw new Error("Fonte local inválida.");
      }
      return { id: source.id, kind: source.kind, domain_id: "dom_synthetic_a", snippet: source.snippet };
    });
    if ((read.status === "evidence") !== (sources.length > 0 && read.text.length > 0) ||
        (read.status !== "evidence" && (sources.length !== 0 || read.text.length !== 0)) ||
        sources.map((source) => source.snippet).join(" | ") !== read.text) {
      throw new Error("Evidência local inconsistente.");
    }
    result.grounded_read = {
      status: read.status as GroundedReadResult["status"], reason: read.reason,
      provider_id: "fake-deterministic", cost: "unmeasured", text: read.text,
      omitted: read.omitted, sources,
    };
  }
  if (record.task !== undefined) result.task = parseWorkflowTask(record.task);
  if (record.tasks !== undefined) {
    if (!Array.isArray(record.tasks) || record.tasks.length > 4) throw new Error("Lista de workflows inválida.");
    result.tasks = record.tasks.map(parseWorkflowTaskSummary);
  }
  if (record.error !== undefined) {
    if (typeof record.error !== "string") throw new Error("Erro G5 inválido.");
    result.error = record.error;
  }
  if (record.session_active !== undefined) {
    if (typeof record.session_active !== "boolean") throw new Error("Sessão G5 inválida.");
    result.session_active = record.session_active;
  }
  if (record.grant_active !== undefined) {
    if (typeof record.grant_active !== "boolean") throw new Error("Concessão G5 inválida.");
    result.grant_active = record.grant_active;
  }
  if (record.expires_at !== undefined) {
    if (typeof record.expires_at !== "string") throw new Error("Validade G5 inválida.");
    result.expires_at = record.expires_at;
  }
  if (record.domain_id !== undefined) {
    if (record.domain_id !== "dom_synthetic_a") throw new Error("Domínio G5 inválido.");
    result.domain_id = "dom_synthetic_a";
  }
  if (record.dataset !== undefined) {
    if (record.dataset !== "api_synthetic") throw new Error("Fonte G5 inválida.");
    result.dataset = "api_synthetic";
  }
  if (record.items !== undefined) {
    if (!Array.isArray(record.items)) throw new Error("Lista de missões inválida.");
    const items = record.items.map((item): G5Mission => {
      if (typeof item !== "object" || item === null) throw new Error("Missão inválida.");
      const mission = item as Record<string, unknown>;
      if (typeof mission.id !== "string" || typeof mission.title !== "string" ||
          mission.id.length === 0 || mission.id.length > 128 || /[\u0000-\u001f\u007f]/.test(mission.id) ||
          [...mission.title].length > 80 || mission.domain_id !== "dom_synthetic_a" ||
          typeof mission.status !== "string" ||
          !["draft", "planned", "awaiting_approval", "running", "blocked", "done", "cancelled", "failed", "interrupted"].includes(mission.status) ||
          typeof mission.revision !== "number" || !Number.isSafeInteger(mission.revision) || mission.revision < 0) {
        throw new Error("Missão inválida.");
      }
      return mission as G5Mission;
    });
    result.items = items;
  }
  if (record.cleared !== undefined) {
    if (record.cleared !== true) throw new Error("Limpeza de captura inválida.");
    result.cleared = true;
  }
  if (record.deleted !== undefined) {
    if (record.deleted !== true) throw new Error("Apagar captura inválido.");
    result.deleted = true;
  }
  if (record.cancelled !== undefined) {
    if (record.ok !== true || Object.keys(record).length !== 2 || record.cancelled !== true) throw new Error("Cancelamento de conversa inválido.");
    result.cancelled = true;
  }
  if (record.exported !== undefined) {
    if (record.ok !== true || Object.keys(record).length !== 2 || record.exported !== true) throw new Error("Exportação de memória inválida.");
    result.exported = true;
  }
  if (record.automations !== undefined) {
    if (!Array.isArray(record.automations) || record.automations.length > 3) throw new Error("Lista de automações inválida.");
    result.automations = record.automations.map(parseLocalAutomation);
  }
  if (record.automation !== undefined) result.automation = parseLocalAutomation(record.automation);
  if (record.runs !== undefined) {
    if (!Array.isArray(record.runs) || record.runs.length > 5) throw new Error("Histórico inválido.");
    result.runs = record.runs.map((run) => parseLocalAutomationRun(run, false));
  }
  if (record.run !== undefined) result.run = parseLocalAutomationRun(record.run, true);
  if (record.id !== undefined) {
    if (typeof record.id !== "string" || !/^[0-9a-f]{32}$/.test(record.id)) throw new Error("Identificador de automação inválido.");
    result.id = record.id;
  }
  if (record.timezone !== undefined) {
    if (typeof record.timezone !== "string" || record.timezone.length < 1 || record.timezone.length > 64 || /[\u0000-\u001f\u007f]/.test(record.timezone)) throw new Error("Fuso horário inválido.");
    result.timezone = record.timezone;
  }
  if (record.next_run_at !== undefined) {
    if (typeof record.next_run_at !== "string" || (record.next_run_at !== "" && !validAutomationTimestamp(record.next_run_at))) throw new Error("Próxima execução inválida.");
    result.next_run_at = record.next_run_at;
  }
  if (record.state !== undefined) {
    if (typeof record.state !== "string" || !["active", "paused", "completed", "deleted"].includes(record.state)) throw new Error("Estado da automação inválido.");
    result.state = record.state as G5CommandResult["state"];
  }
  if (record.workflow_version !== undefined) {
    if (typeof record.workflow_version !== "string" || !["reminder.v1", "morning-briefing.v1", "idea-mission-review.v1"].includes(record.workflow_version)) throw new Error("Versão do workflow inválida.");
    result.workflow_version = record.workflow_version;
  }
  if (record.review_grant !== undefined) {
    if (record.review_grant !== true) throw new Error("Concessão de revisão inválida.");
    result.review_grant = true;
  }
  if (record.review_grant_revoked !== undefined) {
    if (record.review_grant_revoked !== true) throw new Error("Revogação de revisão inválida.");
    result.review_grant_revoked = true;
  }
  if (record.queued !== undefined) {
    if (typeof record.queued !== "boolean") throw new Error("Rascunho de revisão inválido.");
    result.queued = record.queued;
  }
  if (record.review_detail !== undefined) {
    if (typeof record.review_detail !== "object" || record.review_detail === null) {
      throw new Error("Detalhe de revisão inválido.");
    }
    const review = record.review_detail as Record<string, unknown>;
    if (typeof review.id !== "string" || !/^[A-Za-z0-9_-]{8,128}$/.test(review.id) ||
        typeof review.title !== "string" || [...review.title].length < 1 || [...review.title].length > 80 ||
        /[\u0000-\u001f\u007f]/.test(review.title) ||
        typeof review.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(review.sha256) ||
        typeof review.revision !== "number" || !Number.isSafeInteger(review.revision) || review.revision < 1 ||
        typeof review.content !== "string" || review.content.length === 0 || [...review.content].length > 2048 ||
        /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(review.content)) {
      throw new Error("Detalhe de revisão inválido.");
    }
    result.review_detail = {
      id: review.id,
      revision: review.revision,
      sha256: review.sha256,
      title: review.title,
      content: review.content,
    };
  }
  if (record.approved !== undefined) {
    if (record.approved !== true) throw new Error("Decisão de revisão inválida.");
    result.approved = true;
  }
  if (record.replayed !== undefined) {
    if (typeof record.replayed !== "boolean") throw new Error("Repetição de revisão inválida.");
    result.replayed = record.replayed;
  }
  if (record.reviews !== undefined) {
    if (!Array.isArray(record.reviews)) throw new Error("Fila de revisão inválida.");
    result.reviews = record.reviews.map((item) => {
      if (typeof item !== "object" || item === null) throw new Error("Revisão inválida.");
      const review = item as Record<string, unknown>;
      if (typeof review.id !== "string" || !/^[A-Za-z0-9_-]{8,128}$/.test(review.id) ||
          typeof review.title !== "string" || [...review.title].length < 1 || [...review.title].length > 80 ||
          /[\u0000-\u001f\u007f]/.test(review.title) ||
          typeof review.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(review.sha256) ||
          typeof review.revision !== "number" || !Number.isSafeInteger(review.revision) || review.revision < 1) {
        throw new Error("Revisão inválida.");
      }
      return { id: review.id, revision: review.revision, sha256: review.sha256, title: review.title };
    });
  }
  if (record.captures !== undefined || record.origin !== undefined) {
    const allowed = new Set(["ok", "captures", "origin", "omitted"]);
    if (Object.keys(record).some((key) => !allowed.has(key))) {
      throw new Error("Campo de captura desconhecido.");
    }
  }
  if (record.origin !== undefined) {
    if (typeof record.origin !== "object" || record.origin === null || Array.isArray(record.origin)) {
      throw new Error("Origem da captura inválida.");
    }
    const origin = record.origin as Record<string, unknown>;
    const originKeys = ["id", "text", "created_at", "domain_id", "category"];
    if (Object.keys(origin).length !== originKeys.length || originKeys.some((key) => !(key in origin))) {
      throw new Error("Origem da captura inválida.");
    }
    if (typeof origin.id !== "string" || !/^[0-9a-f]{32}$/.test(origin.id) ||
        typeof origin.text !== "string" || origin.text.length === 0 || [...origin.text].length > 80 ||
        /[\u0000-\u001f\u007f]/.test(origin.text) || typeof origin.created_at !== "string" ||
        origin.domain_id !== "dom_synthetic_a" || origin.category !== "explicit_capture") {
      throw new Error("Origem da captura inválida.");
    }
    result.origin = {
      id: origin.id,
      text: origin.text,
      created_at: origin.created_at,
      domain_id: "dom_synthetic_a",
      category: "explicit_capture",
    };
  }
  if (record.captures !== undefined) {
    if (!Array.isArray(record.captures) || record.captures.length > 3) throw new Error("Lista de capturas inválida.");
    result.captures = record.captures.map((item): LocalCapture => {
      if (typeof item !== "object" || item === null || Array.isArray(item)) throw new Error("Captura inválida.");
      const capture = item as Record<string, unknown>;
      const captureKeys = ["id", "text", "created_at"];
      if (Object.keys(capture).length !== captureKeys.length || captureKeys.some((key) => !(key in capture))) {
        throw new Error("Captura inválida.");
      }
      if (typeof capture.id !== "string" || !/^[0-9a-f]{32}$/.test(capture.id) ||
          typeof capture.text !== "string" || capture.text.length === 0 || [...capture.text].length > 80 ||
          /[\u0000-\u001f\u007f]/.test(capture.text) || typeof capture.created_at !== "string") {
        throw new Error("Captura inválida.");
      }
      return { id: capture.id, text: capture.text, created_at: capture.created_at };
    });
    if (record.omitted !== undefined) {
      if (typeof record.omitted !== "number" || !Number.isSafeInteger(record.omitted) || record.omitted < 0) {
        throw new Error("Contagem de capturas omitidas inválida.");
      }
      if (result.captures.length < 3 && record.omitted !== 0) throw new Error("Contagem de capturas omitidas inválida.");
      result.omitted = record.omitted;
    }
  }
  if (record.created_at !== undefined) {
    if (typeof record.id !== "string" || typeof record.created_at !== "string") throw new Error("Captura inválida.");
    result.id = record.id;
    result.created_at = record.created_at;
  }
  if ((result.dataset === "api_synthetic") !== (result.items !== undefined)) {
    throw new Error("Resposta de missões inválida.");
  }
  return result;
}

export type WorkflowPageResult = { ok: true; tasks: WorkflowTaskSummary[]; next_cursor: string } | { ok: false; error: string };

function validWorkflowCursor(cursor: string): boolean {
  if (typeof cursor !== "string") return false;
  if (cursor === "") return true;
  if (cursor.length > 80 || !/^wf1\|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?\+00:00\|[0-9a-f]{32}$/.test(cursor) || cursor.includes(".000000+")) return false;
  const stamp = cursor.split("|")[1];
  const year = Number(stamp.slice(0, 4)), month = Number(stamp.slice(5, 7)), day = Number(stamp.slice(8, 10));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1] &&
    Number(stamp.slice(11, 13)) < 24 && Number(stamp.slice(14, 16)) < 60 && Number(stamp.slice(17, 19)) < 60;
}

export function parseWorkflowPageResult(raw: unknown, requested = ""): WorkflowPageResult {
  if (!validWorkflowCursor(requested) || typeof raw !== "string" || new TextEncoder().encode(raw).length >= 2048) throw new Error("Página local inválida.");
  const value = JSON.parse(raw) as Record<string, unknown>;
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Página local inválida.");
  if (value.ok === false && Object.keys(value).length === 2 && typeof value.error === "string") return { ok: false, error: value.error };
  if (value.ok !== true || Object.keys(value).length !== 3 || !Array.isArray(value.tasks) || value.tasks.length > 4 ||
      typeof value.next_cursor !== "string" || !validWorkflowCursor(value.next_cursor)) throw new Error("Página local inválida.");
  const keys = ["task_id", "tool_id", "state", "arguments_sha", "created_at", "updated_at", "risk", "expected_effect"];
  let previous = requested ? requested.split("|").slice(1).join("|") : "";
  let lastCursor = "";
  const tasks = value.tasks.map((entry: unknown) => {
    const item = parseWorkflowTaskSummary(entry);
    if (Object.keys(item).length !== keys.length || keys.some((key) => !(key in item))) throw new Error("Página local inválida.");
    lastCursor = `wf1|${item.created_at}|${item.task_id}`;
    const key = `${item.created_at}|${item.task_id}`;
    if (!validWorkflowCursor(lastCursor) || (previous && key >= previous)) throw new Error("Ordem de histórico inválida.");
    previous = key;
    return item;
  });
  if (value.next_cursor && (tasks.length === 0 || value.next_cursor !== lastCursor)) throw new Error("Cursor de histórico inválido.");
  return { ok: true, tasks, next_cursor: value.next_cursor };
}

function parseWorkflowTaskSummary(value: unknown): WorkflowTaskSummary {
  if (typeof value !== "object" || value === null) throw new Error("Tarefa local inválida.");
  const item = value as Record<string, unknown>;
  const states: WorkflowState[] = ["proposed", "awaiting_approval", "paused", "running", "interrupted", "succeeded", "failed", "cancelled"];
  if (typeof item.task_id !== "string" || !/^[0-9a-f]{32}$/.test(item.task_id) ||
      (item.tool_id !== "draft_note" && item.tool_id !== "simulate_action") ||
      typeof item.state !== "string" || !states.includes(item.state as WorkflowState) ||
      typeof item.arguments_sha !== "string" || !/^[0-9a-f]{64}$/.test(item.arguments_sha) ||
      typeof item.created_at !== "string" || typeof item.updated_at !== "string" ||
      (item.risk !== "low" && item.risk !== "medium") || typeof item.expected_effect !== "string") {
    throw new Error("Tarefa local inválida.");
  }
  return item as WorkflowTaskSummary;
}

function parseWorkflowTask(value: unknown): WorkflowTask {
  const summary = parseWorkflowTaskSummary(value);
  const item = value as Record<string, unknown>;
  if (typeof item.idempotency_key !== "string" || !/^[A-Za-z0-9_-]{8,80}$/.test(item.idempotency_key) ||
      typeof item.permission !== "string" || typeof item.timeout_ms !== "number" ||
      !Number.isSafeInteger(item.timeout_ms) || item.timeout_ms < 1 ||
      typeof item.limit !== "number" || item.limit !== 1 || typeof item.enabled !== "boolean" ||
      typeof item.retry !== "object" || item.retry === null) throw new Error("Metadados de workflow inválidos.");
  const retry = item.retry as Record<string, unknown>;
  if (typeof retry.max_attempts !== "number" || !Number.isSafeInteger(retry.max_attempts) ||
      retry.max_attempts < 1 || !Array.isArray(retry.retryable) || retry.retryable.some((entry) => typeof entry !== "string")) {
    throw new Error("Política de retry inválida.");
  }
  let preview: WorkflowPreview | undefined;
  if (item.preview !== undefined) {
    if (typeof item.preview !== "object" || item.preview === null) throw new Error("Prévia de simulação inválida.");
    const candidate = item.preview as Record<string, unknown>;
    if (typeof candidate.service !== "string" || typeof candidate.account !== "string" ||
        typeof candidate.target !== "string" || typeof candidate.consequence !== "string" ||
        candidate.risk !== "medium" || !Array.isArray(candidate.data_sent) || candidate.data_sent.length !== 0 ||
        typeof candidate.payload !== "object" || candidate.payload === null) throw new Error("Prévia de simulação inválida.");
    const payload = candidate.payload as Record<string, unknown>;
    if (typeof payload.subject !== "string" || typeof payload.body !== "string" ||
        [...payload.subject].length > 30 || [...payload.body].length > 80 ||
        /[\u0000-\u001f\u007f]/.test(payload.subject + payload.body)) throw new Error("Payload de simulação inválido.");
    preview = candidate as WorkflowPreview;
  }
  return { ...summary, idempotency_key: item.idempotency_key, permission: item.permission,
    timeout_ms: item.timeout_ms, limit: item.limit, retry: retry as WorkflowTask["retry"],
    enabled: item.enabled, preview,
    ...(typeof item.result === "object" && item.result !== null ? { result: item.result as Record<string, unknown> } : {}),
    ...(typeof item.result_sha === "string" && /^[0-9a-f]{64}$/.test(item.result_sha) ? { result_sha: item.result_sha } : {}),
    ...(typeof item.effect === "string" ? { effect: item.effect } : {}),
    ...(typeof item.attempts === "number" && Number.isSafeInteger(item.attempts) ? { attempts: item.attempts } : {}),
  };
}

function validAutomationTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));
}

function parseLocalAutomation(value: unknown): LocalAutomation {
  if (typeof value !== "object" || value === null) throw new Error("Automação inválida.");
  const item = value as Record<string, unknown>;
  const kinds = ["reminder", "morning_briefing", "idea_mission_review"] as const;
  const recurrence = ["once", "daily"] as const;
  const states = ["active", "paused", "completed", "deleted"] as const;
  if (typeof item.id !== "string" || !/^[0-9a-f]{32}$/.test(item.id) ||
      typeof item.kind !== "string" || !kinds.includes(item.kind as typeof kinds[number]) ||
      typeof item.recurrence !== "string" || !recurrence.includes(item.recurrence as typeof recurrence[number]) ||
      typeof item.state !== "string" || !states.includes(item.state as typeof states[number]) ||
      typeof item.title !== "string" || item.title.length < 1 || [...item.title].length > 24 || /[\u0000-\u001f\u007f]/.test(item.title) ||
      typeof item.local_schedule !== "string" || item.local_schedule.length > 16 || /[\u0000-\u001f\u007f]/.test(item.local_schedule) ||
      typeof item.timezone !== "string" || item.timezone.length < 1 || item.timezone.length > 64 || /[\u0000-\u001f\u007f]/.test(item.timezone) ||
      typeof item.next_run_at !== "string" || (item.next_run_at !== "" && !validAutomationTimestamp(item.next_run_at)) ||
      typeof item.workflow_version !== "string" || !["reminder.v1", "morning-briefing.v1", "idea-mission-review.v1"].includes(item.workflow_version) ||
      typeof item.quiet_start !== "string" || typeof item.quiet_end !== "string" ||
      !Array.isArray(item.sources) || item.sources.some((source) => typeof source !== "string" || source.length > 64)) {
    throw new Error("Automação inválida.");
  }
  const expectedWorkflow = item.kind === "reminder" ? "reminder.v1"
    : item.kind === "morning_briefing" ? "morning-briefing.v1" : "idea-mission-review.v1";
  const expectedSources = item.kind === "reminder" ? ["user-authored-reminder"] : ["local_captures", "missions:dom_synthetic_a"];
  if (item.workflow_version !== expectedWorkflow || JSON.stringify(item.sources) !== JSON.stringify(expectedSources)) {
    throw new Error("Proveniência da automação inválida.");
  }
  if ((item.quiet_start !== "" && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(item.quiet_start)) ||
      (item.quiet_end !== "" && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(item.quiet_end)) ||
      ((item.quiet_start === "") !== (item.quiet_end === ""))) throw new Error("Janela silenciosa inválida.");
  if ((item.recurrence === "daily" && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(item.local_schedule)) ||
      (item.recurrence === "once" && !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d$/.test(item.local_schedule))) {
    throw new Error("Horário da automação inválido.");
  }
  if (item.kind === "reminder" && item.message !== undefined) {
    if (typeof item.message !== "string" || [...item.message].length < 1 || [...item.message].length > 32 || /[\u0000-\u001f\u007f]/.test(item.message)) {
      throw new Error("Lembrete inválido.");
    }
  }
  return {
    id: item.id, kind: item.kind as LocalAutomation["kind"], title: item.title,
    recurrence: item.recurrence as LocalAutomation["recurrence"], local_schedule: item.local_schedule,
    timezone: item.timezone, state: item.state as LocalAutomation["state"], next_run_at: item.next_run_at,
    workflow_version: item.workflow_version, sources: item.sources as string[],
    quiet_start: item.quiet_start, quiet_end: item.quiet_end,
    ...(typeof item.message === "string" ? { message: item.message } : {}),
  };
}

function parseLocalAutomationRun(value: unknown, withOutput: boolean): LocalAutomationRun {
  if (typeof value !== "object" || value === null) throw new Error("Execução inválida.");
  const item = value as Record<string, unknown>;
  const states = ["running", "deferred", "retry_wait", "succeeded", "failed", "missed", "pending", "superseded"];
  if (typeof item.id !== "string" || !/^[0-9a-f]{32}$/.test(item.id) ||
      !validAutomationTimestamp(item.scheduled_for) || typeof item.status !== "string" || !states.includes(item.status) ||
      (item.attempts !== undefined && (typeof item.attempts !== "number" || !Number.isSafeInteger(item.attempts) || item.attempts < 0 || item.attempts > 3)) ||
      (!withOutput && item.attempts === undefined) ||
      typeof item.error_code !== "string" || item.error_code.length > 64 || /[\u0000-\u001f\u007f]/.test(item.error_code) ||
      (item.completed_at !== undefined && (typeof item.completed_at !== "string" || (item.completed_at !== "" && !validAutomationTimestamp(item.completed_at)))) ||
      (!withOutput && item.completed_at === undefined) ||
      typeof item.workflow_version !== "string" || !["reminder.v1", "morning-briefing.v1", "idea-mission-review.v1"].includes(item.workflow_version) ||
      (withOutput && (typeof item.output !== "string" || [...item.output].length > 80 || /[\u0000-\u001f\u007f]/.test(item.output)))) {
    throw new Error("Execução inválida.");
  }
  const allowedSources = ["user-authored-reminder", "local_captures", "missions:dom_synthetic_a", "local-empty-state"];
  let sources: string[];
  if (withOutput) {
    if (!Array.isArray(item.sources) || item.sources.length > 4) throw new Error("Proveniência da execução inválida.");
    sources = item.sources.map((source) => {
      if (typeof source !== "object" || source === null) throw new Error("Proveniência da execução inválida.");
      const ref = source as Record<string, unknown>;
      if (typeof ref.source !== "string" || !allowedSources.includes(ref.source) ||
          typeof ref.id !== "string" || (!/^[0-9a-f]{32}$/.test(ref.id) && ref.id !== "dom_synthetic_a") ||
          !validAutomationTimestamp(ref.observed_at)) throw new Error("Proveniência da execução inválida.");
      return ref.source + " · " + ref.id + " · " + ref.observed_at;
    });
  } else {
    if (typeof item.sources !== "string" || item.sources.length > 128 || /[\u0000-\u001f\u007f]/.test(item.sources)) {
      throw new Error("Proveniência da execução inválida.");
    }
    sources = item.sources ? item.sources.split(",") : [];
    if (sources.some((source) => !allowedSources.includes(source))) throw new Error("Proveniência da execução inválida.");
  }
  return {
    id: item.id, scheduled_for: item.scheduled_for, status: item.status as LocalAutomationRun["status"],
    attempts: typeof item.attempts === "number" ? item.attempts : 0, error_code: item.error_code,
    completed_at: typeof item.completed_at === "string" ? item.completed_at : "",
    workflow_version: item.workflow_version, sources,
    ...(typeof item.output === "string" ? { output: item.output } : {}),
  };
}

export function parseConnectorStatus(value: string): ConnectorStatus {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null) throw new Error("Conector inválido.");
  const record = parsed as Record<string, unknown>;
  const block = record.gmail_block;
  if (record.ok !== true || record.gmail !== "not_connected" || record.calendar !== "not_connected" ||
      record.calendar_sim !== "synthetic_local" || record.gmail_scope !== "gmail.readonly" ||
      record.calendar_scope !== "calendar.readonly" ||
      (block !== "missing_oauth_client" && block !== "consent_required") ||
      record.calendar_block !== block) {
    throw new Error("Conector inválido.");
  }
  return {
    ok: true,
    gmail: "not_connected",
    gmail_block: block,
    gmail_scope: "gmail.readonly",
    calendar: "not_connected",
    calendar_block: block,
    calendar_scope: "calendar.readonly",
    calendar_sim: "synthetic_local",
  };
}

export function parseLocalRuntimeConfig(value: string): LocalRuntimeConfig {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null) throw new Error("Configuração local inválida.");
  const record = parsed as Record<string, unknown>;
  const flag = (key: string) => {
    if (typeof record[key] !== "boolean") throw new Error("Configuração local inválida.");
    return record[key] as boolean;
  };
  if (record.ok !== true) throw new Error("Configuração local inválida.");
  if (record.database_mode !== "stable" && record.database_mode !== "override") {
    throw new Error("Configuração local inválida.");
  }
  return {
    ok: true,
    passphrase_configured: flag("passphrase_configured"),
    database_configured: flag("database_configured"),
    database_mode: record.database_mode,
    api_root_configured: flag("api_root_configured"),
    oauth_client_configured: flag("oauth_client_configured"),
  };
}

export async function executeRuntimeCommand(
  command: RuntimeCommand,
  invokeRuntime: (command: RuntimeCommand | "runtime_status") => Promise<string>,
): Promise<{ operation: RuntimeEnvelope; current: RuntimeEnvelope }> {
  const operation = parseRuntimeEnvelope(await invokeRuntime(command));
  // The command describes its operation; the visible state comes from status.
  const current = parseRuntimeEnvelope(await invokeRuntime("runtime_status"));
  return { operation, current };
}
