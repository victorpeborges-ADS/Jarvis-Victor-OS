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
  grant_active: boolean;
  grant_domain_id: string | null;
  grant_expires_at: string | null;
};

export type G5Mission = {
  id: string;
  title: string;
  domain_id: "dom_synthetic_a";
  status: "draft" | "planned" | "awaiting_approval" | "running" | "blocked" | "done" | "cancelled" | "failed" | "interrupted";
  revision: number;
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
};

type G5Invoke = (command: string, args?: Record<string, unknown>) => Promise<string>;

export function createG5Ipc(invokeG5: G5Invoke) {
  return {
    sessionStatus: async (): Promise<G5SessionSnapshot> =>
      parseG5SessionSnapshot(await invokeG5("g5_session_status")),
    openSession: async (passphrase: string): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_session_open", { passphrase })),
    createMissionReadGrant: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_mission_read_grant_create")),
    revokeMissionReadGrant: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_mission_read_grant_revoke")),
    closeSession: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_session_close")),
    listMissions: async (): Promise<G5CommandResult> =>
      parseG5CommandResult(await invokeG5("g5_missions_list")),
  };
}

const states: RuntimeState[] = ["STOPPED", "STARTING", "READY", "STOPPING", "FAILED", "CRASHED"];
const transportStates: TransportState[] = ["DISCONNECTED", "DISCOVERING", "PROVING_INSTANCE", "READY", "INCOMPATIBLE", "FAILED"];

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
  return {
    ok: true,
    session_active: record.session_active,
    session_expires_at: optionalText("session_expires_at"),
    grant_active: record.grant_active,
    grant_domain_id: optionalText("grant_domain_id"),
    grant_expires_at: optionalText("grant_expires_at"),
  };
}

export function parseG5CommandResult(value: string): G5CommandResult {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null || typeof (parsed as Record<string, unknown>).ok !== "boolean") {
    throw new Error("Resposta G5 inválida.");
  }
  const record = parsed as Record<string, unknown>;
  const result: G5CommandResult = { ok: record.ok as boolean };
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
  if ((result.dataset === "api_synthetic") !== (result.items !== undefined)) {
    throw new Error("Resposta de missões inválida.");
  }
  return result;
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
