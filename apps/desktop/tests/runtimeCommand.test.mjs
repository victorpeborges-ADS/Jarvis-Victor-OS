import assert from "node:assert/strict";
import test from "node:test";
import { createG5Ipc, executeRuntimeCommand, grantIsDisplayedActive, parseG5CommandResult, parseG5SessionSnapshot, parseTransportSnapshot } from "../src/runtimeCommand.ts";

test("concessão exibida segue o instante do servidor, não o rótulo", () => {
  const future = Date.now() * 1000 + 60_000_000;
  const active = parseG5SessionSnapshot(JSON.stringify({
    ok: true, session_active: true, session_expires_at: "2026-10-11T20:00:00+00:00",
    session_expires_at_epoch_us: future, grant_active: true, grant_domain_id: "dom_synthetic_a",
    grant_expires_at: "texto que não autoriza", grant_expires_at_epoch_us: future,
  }));
  assert.equal(grantIsDisplayedActive(active, Date.now()), true);
  assert.equal(grantIsDisplayedActive({ ...active, grant_expires_at_epoch_us: Date.now() * 1000 - 1 }, Date.now()), false);
  assert.equal(grantIsDisplayedActive({ ...active, grant_expires_at_epoch_us: null }, Date.now()), false);
});

function envelope(state, id) {
  return JSON.stringify({
    ok: true,
    snapshot: {
      state,
      runtime_instance_id: id,
      pid: null,
      started_at_unix_ms: null,
      ready_at_unix_ms: null,
      exit_code: null,
      failure_category: null,
    },
    error: null,
  });
}

test("stop result belongs to A while the displayed status belongs to B", async () => {
  const calls = [];
  const invoke = async (command) => {
    calls.push(command);
    return command === "runtime_stop" ? envelope("STOPPED", "A") : envelope("READY", "B");
  };
  const { operation, current } = await executeRuntimeCommand("runtime_stop", invoke);
  assert.deepEqual(calls, ["runtime_stop", "runtime_status"]);
  assert.equal(operation.snapshot.runtime_instance_id, "A");
  assert.equal(current.snapshot.runtime_instance_id, "B");
  assert.equal(current.snapshot.state, "READY");
});

test("transport status exposes only typed state and UDS protocol metadata", () => {
  const status = parseTransportSnapshot(JSON.stringify({
    state: "READY",
    runtime_instance_id: "A",
    endpoint_type: "uds",
    protocol_version: "1",
    error_category: null,
    secret: "não deve atravessar IPC",
    socket_path: "/private/jv.sock",
  }));
  assert.equal(status.state, "READY");
  assert.equal(status.endpoint_type, "uds");
  assert.equal("secret" in status, false);
  assert.equal("socket_path" in status, false);
  assert.throws(() => parseTransportSnapshot(JSON.stringify({ state: "READY", endpoint_type: "tcp" })));
});

test("G5 status and result parsers do not forward credentials or unknown fields", () => {
  const status = parseG5SessionSnapshot(JSON.stringify({
    ok: true,
    session_active: true,
    session_expires_at: "2026-10-06T12:00:00+00:00",
    grant_active: false,
    grant_domain_id: null,
    grant_expires_at: null,
    session_token: "synthetic-secret",
  }));
  assert.equal(status.session_active, true);
  assert.equal("session_token" in status, false);

  const result = parseG5CommandResult(JSON.stringify({
    ok: true,
    dataset: "api_synthetic",
    items: [{ id: "mission_0123456789abcdef", title: "Missão sintética", domain_id: "dom_synthetic_a", status: "planned", revision: 1 }],
    csrf_token: "synthetic-secret",
  }));
  assert.equal(result.items?.[0]?.title, "Missão sintética");
  assert.equal("csrf_token" in result, false);
  assert.throws(() => parseG5CommandResult(JSON.stringify({
    ok: true,
    dataset: "api_synthetic",
    items: [{ id: "mission_1", title: "Tarefa", domain_id: "dom_synthetic_a", status: "unknown", revision: 0 }],
  })));
});

test("aprovação local não encaminha rota nem segredo", () => {
  const result = parseG5CommandResult(JSON.stringify({
    ok: true,
    approved: true,
    replayed: false,
    url: "https://example.invalid/approve",
    session_token: "synthetic-secret",
  }));
  assert.equal(result.approved, true);
  assert.equal(result.replayed, false);
  assert.equal("url" in result, false);
  assert.equal("session_token" in result, false);
});

test("G5 IPC exposes only the fixed typed operations", async () => {
  const calls = [];
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    if (command === "g5_session_status") return JSON.stringify({
      ok: true, session_active: false, session_expires_at: null,
      grant_active: false, grant_domain_id: null, grant_expires_at: null,
    });
    return JSON.stringify({ ok: true, session_active: true });
  });
  await ipc.sessionStatus();
  const opened = await ipc.openSession("senha sintética de teste");
  await ipc.createMissionReadGrant();
  await ipc.revokeMissionReadGrant();
  await ipc.listMissions();
  await ipc.closeSession();
  assert.deepEqual(calls.map(({ command }) => command), [
    "g5_session_status", "g5_session_open", "g5_mission_read_grant_create",
    "g5_mission_read_grant_revoke", "g5_missions_list", "g5_session_close",
  ]);
  assert.deepEqual(calls[1].args, { passphrase: "senha sintética de teste" });
  assert.equal(opened.session_active, true);
});
