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

const states: RuntimeState[] = ["STOPPED", "STARTING", "READY", "STOPPING", "FAILED", "CRASHED"];

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

export async function executeRuntimeCommand(
  command: RuntimeCommand,
  invokeRuntime: (command: RuntimeCommand | "runtime_status") => Promise<string>,
): Promise<{ operation: RuntimeEnvelope; current: RuntimeEnvelope }> {
  const operation = parseRuntimeEnvelope(await invokeRuntime(command));
  // The command describes its operation; the visible state comes from status.
  const current = parseRuntimeEnvelope(await invokeRuntime("runtime_status"));
  return { operation, current };
}
