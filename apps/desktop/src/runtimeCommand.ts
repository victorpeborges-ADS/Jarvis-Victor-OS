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
export type RuntimeCommand = "runtime_start_test" | "runtime_stop" | "runtime_restart_test";
export type TransportState = "DISCONNECTED" | "DISCOVERING" | "PROVING_INSTANCE" | "READY" | "INCOMPATIBLE" | "FAILED";
export type TransportSnapshot = {
  state: TransportState;
  runtime_instance_id: string | null;
  endpoint_type: "uds" | null;
  protocol_version: string | null;
  error_category: string | null;
};

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

export async function executeRuntimeCommand(
  command: RuntimeCommand,
  invokeRuntime: (command: RuntimeCommand | "runtime_status") => Promise<string>,
): Promise<{ operation: RuntimeEnvelope; current: RuntimeEnvelope }> {
  const operation = parseRuntimeEnvelope(await invokeRuntime(command));
  // The command describes its operation; the visible state comes from status.
  const current = parseRuntimeEnvelope(await invokeRuntime("runtime_status"));
  return { operation, current };
}
