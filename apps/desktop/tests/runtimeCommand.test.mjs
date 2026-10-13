import assert from "node:assert/strict";
import test from "node:test";
import { createG5Ipc, executeRuntimeCommand, grantIsDisplayedActive, parseG5CommandResult, parseG5SessionSnapshot, parseLocalRuntimeConfig, parseTransportSnapshot } from "../src/runtimeCommand.ts";

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

test("configuração distingue banco diário de override sem expor caminho", () => {
  const stable = parseLocalRuntimeConfig(JSON.stringify({
    ok: true, passphrase_configured: true, database_configured: false,
    database_mode: "stable", api_root_configured: true, oauth_client_configured: false,
    database_path: "/caminho/sensível.sqlite3",
  }));
  const override = parseLocalRuntimeConfig(JSON.stringify({
    ok: true, passphrase_configured: true, database_configured: true,
    database_mode: "override", api_root_configured: true, oauth_client_configured: false,
  }));
  assert.equal(stable.database_mode, "stable");
  assert.equal(override.database_mode, "override");
  assert.equal("database_path" in stable, false);
  assert.throws(() => parseLocalRuntimeConfig(JSON.stringify({
    ok: true, passphrase_configured: true, database_configured: true,
    database_mode: "unknown", api_root_configured: true, oauth_client_configured: false,
  })));
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
    if (command === "g5_review_draft") return JSON.stringify({ ok: true, queued: true });
    return JSON.stringify({ ok: true, session_active: true });
  });
  await ipc.sessionStatus();
  const opened = await ipc.openSession();
  await ipc.createMissionReadGrant();
  await ipc.revokeMissionReadGrant();
  await ipc.revokeReviewGrant();
  await ipc.listMissions();
  const review = { id: "review_12345678", revision: 1, sha256: "a".repeat(64), title: "Rascunho local" };
  await ipc.pendingReviews();
  const draft = await ipc.queueReviewDraft();
  await ipc.reviewDetail(review);
  await ipc.approveReview({ ...review, content: "Texto sintético" });
  await ipc.closeSession();
  assert.deepEqual(calls.map(({ command }) => command), [
    "g5_session_status", "g5_session_open", "g5_mission_read_grant_create",
    "g5_mission_read_grant_revoke", "g5_review_grant_revoke", "g5_missions_list", "g5_reviews_pending",
    "g5_review_draft", "g5_review_detail", "g5_review_approve", "g5_session_close",
  ]);
  assert.equal(calls[1].args, undefined);
  assert.equal(draft.queued, true);
  assert.deepEqual(calls[8].args, { reviewId: review.id, revision: 1, sha256: review.sha256 });
  assert.deepEqual(calls[9].args, { reviewId: review.id, revision: 1, sha256: review.sha256 });
  assert.equal(opened.session_active, true);
});

test("captura diária usa somente comandos IPC tipados para CRUD", async () => {
  const calls = [];
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    return JSON.stringify({ ok: true, id: "0123456789abcdef0123456789abcdef", created_at: "2026-10-12T12:00:00+00:00" });
  });
  await ipc.createCapture("ideia sintética");
  await ipc.listCaptures();
  await ipc.editCapture("0123456789abcdef0123456789abcdef", "ideia editada");
  await ipc.deleteCapture("0123456789abcdef0123456789abcdef");
  assert.deepEqual(calls, [
    { command: "g5_capture_create", args: { text: "ideia sintética" } },
    { command: "g5_capture_list", args: undefined },
    { command: "g5_capture_edit", args: { capture_id: "0123456789abcdef0123456789abcdef", text: "ideia editada" } },
    { command: "g5_capture_delete", args: { capture_id: "0123456789abcdef0123456789abcdef" } },
  ]);
});

test("parser G5 aceita detalhe tipado e recusa controles antes da UI", () => {
  const detail = {
    id: "review_12345678",
    revision: 2,
    sha256: "b".repeat(64),
    title: "Rascunho sintético",
    content: "Texto como dado, não como instrução.\nSegunda linha.",
  };
  const parsed = parseG5CommandResult(JSON.stringify({
    ok: true,
    review_detail: detail,
    session_token: "segredo que deve ser descartado",
  }));
  assert.deepEqual(parsed.review_detail, detail);
  assert.equal("session_token" in parsed, false);
  assert.throws(() => parseG5CommandResult(JSON.stringify({
    ok: true,
    review_detail: { ...detail, content: "texto\u0000injetado" },
  })));
});

test("workflow IPC permanece fechado e exige objeto de tarefa validado", async () => {
  const calls = [];
  const task = {
    task_id: "a".repeat(32), tool_id: "simulate_action", state: "awaiting_approval",
    arguments_sha: "b".repeat(64), created_at: "2026-10-12T12:00:00+00:00",
    updated_at: "2026-10-12T12:00:00+00:00", risk: "medium", expected_effect: "simulação local sem envio",
    idempotency_key: "workflow-idempotency-1", permission: "mission:review", timeout_ms: 500,
    limit: 1, retry: { max_attempts: 2, retryable: ["transient_local"] }, enabled: true,
    preview: {
      service: "E-mail sintético (simulação local)", account: "operator@example.test",
      target: "synthetic-outbox", payload: { subject: "Assunto", body: "Corpo sintético" },
      consequence: "Nenhuma mensagem será enviada.", data_sent: [], risk: "medium",
    },
  };
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    if (command === "g5_workflow_list") return JSON.stringify({ ok: true, tasks: [{
      task_id: task.task_id, tool_id: task.tool_id, state: task.state,
      arguments_sha: task.arguments_sha, created_at: task.created_at, updated_at: task.updated_at,
      risk: task.risk, expected_effect: task.expected_effect,
    }] });
    return JSON.stringify({ ok: true, task });
  });
  await ipc.workflowSubmitSimulation("Assunto", "Corpo sintético");
  await ipc.workflowList();
  const detail = await ipc.workflowDetail(task.task_id);
  await ipc.workflowExecuteSimulation(task.task_id);
  await ipc.workflowPause(task.task_id);
  await ipc.workflowResume(task.task_id);
  await ipc.workflowCancel(task.task_id);
  assert.deepEqual(calls.map(({ command }) => command), [
    "g5_workflow_submit_simulation", "g5_workflow_list", "g5_workflow_detail",
    "g5_workflow_execute_simulation", "g5_workflow_pause", "g5_workflow_resume", "g5_workflow_cancel",
  ]);
  assert.equal(detail.task.preview.data_sent.length, 0);
  assert.equal("url" in calls[0].args, false);
  assert.equal("method" in calls[0].args, false);
  const summary = {
    task_id: task.task_id, tool_id: task.tool_id, state: task.state,
    arguments_sha: task.arguments_sha, created_at: task.created_at, updated_at: task.updated_at,
    risk: task.risk, expected_effect: task.expected_effect,
  };
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, tasks: Array(5).fill(summary) })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, task: { ...task, tool_id: "arbitrary_url" } })));
});


test("automações locais usam somente IPC tipado e descartam campos inesperados", async () => {
  const calls = [];
  const automation = {
    id: "0123456789abcdef0123456789abcdef",
    kind: "reminder",
    title: "Lembrete",
    recurrence: "daily",
    local_schedule: "09:00",
    timezone: "America/Sao_Paulo",
    state: "active",
    next_run_at: "2026-10-13T12:00:00.000000+00:00",
    workflow_version: "reminder.v1",
    sources: ["user-authored-reminder"],
    quiet_start: "",
    quiet_end: "",
    message: "Revisar",
  };
  const run = {
    id: "fedcba9876543210fedcba9876543210",
    scheduled_for: "2026-10-13T12:00:00.000000+00:00",
    status: "succeeded",
    attempts: 1,
    error_code: "",
    completed_at: "2026-10-13T12:00:01.000000+00:00",
    workflow_version: "reminder.v1",
    sources: [{ source: "user-authored-reminder", id: "0123456789abcdef0123456789abcdef", observed_at: "2026-10-12T12:00:00.000000+00:00" }],
    output: "Revisar",
  };
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    if (command === "g5_automations_list") return JSON.stringify({ ok: true, automations: [{ ...automation, message: undefined }], csrf_token: "descartar" });
    if (command === "g5_automation_history") return JSON.stringify({ ok: true, runs: [{ ...run, output: undefined, sources: "user-authored-reminder" }] });
    if (command === "g5_automation_run") return JSON.stringify({ ok: true, run, session_token: "descartar" });
    if (command === "g5_automation_create") return JSON.stringify({ ok: true, id: automation.id, state: "active", next_run_at: automation.next_run_at, workflow_version: "reminder.v1" });
    if (command === "g5_automation_timezone") return JSON.stringify({ ok: true, id: automation.id, timezone: "UTC", next_run_at: automation.next_run_at });
    if (command === "g5_automation_control") return JSON.stringify({ ok: true, id: automation.id, state: "paused", next_run_at: "" });
    return JSON.stringify({ ok: true, automation, secret: "descartar" });
  });
  const listed = await ipc.automationsList();
  const detail = await ipc.automationDetail(automation.id);
  const history = await ipc.automationHistory(automation.id);
  const opened = await ipc.automationRun(automation.id, run.id);
  const created = await ipc.automationCreate({
    kind: "reminder", title: "Lembrete", recurrence: "daily", localSchedule: "09:00",
    timezone: "UTC", quietStart: "", quietEnd: "", message: "Revisar", confirmLocalSources: false,
  });
  await ipc.automationTimezone(automation.id, "UTC");
  await ipc.automationControl(automation.id, "pause");
  assert.equal(listed.automations?.[0]?.sources[0], "user-authored-reminder");
  assert.equal(detail.automation?.workflow_version, "reminder.v1");
  assert.equal(history.runs?.[0]?.status, "succeeded");
  assert.equal(opened.run?.output, "Revisar");
  assert.equal(created.id, automation.id);
  assert.equal("csrf_token" in listed, false);
  assert.deepEqual(calls.map(({ command }) => command), [
    "g5_automations_list", "g5_automation_detail", "g5_automation_history", "g5_automation_run",
    "g5_automation_create", "g5_automation_timezone", "g5_automation_control",
  ]);
  assert.deepEqual(calls[4].args, {
    kind: "reminder", title: "Lembrete", recurrence: "daily", localSchedule: "09:00",
    timezone: "UTC", quietStart: "", quietEnd: "", message: "Revisar", confirmLocalSources: false,
  });
});
