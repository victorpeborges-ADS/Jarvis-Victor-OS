import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { CONVERSATION_ASK_WIRE_FIELDS, CONVERSATION_CANCEL_WIRE_FIELDS, CONVERSATION_OPEN_WIRE_FIELDS, ConversationRequestGate, createG5Ipc, executeRuntimeCommand, grantIsDisplayedActive, parseWorkflowPageResult, parseG5CommandResult, parseG5SessionSnapshot, parseLocalRuntimeConfig, parseTransportSnapshot, STORAGE_ROTATE_FINALIZE_WIRE_FIELDS, STORAGE_ROTATE_RETIRE_WIRE_FIELDS, STORAGE_ROTATE_WIRE_FIELDS, SYNTHETIC_DOCUMENT_WIRE_FIELDS } from "../src/runtimeCommand.ts";

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

test("memória usa IPC fechado, origem validada e exportação sem caminho da WebView", async () => {
  const calls = [];
  const record = {
    id: "0123456789abcdef0123456789abcdef", category: "confirmed_fact", domain_id: "dom_synthetic_b",
    body: "fato sintético confirmado", source_kind: "owner_confirmation", source_ref: "owner-note",
    version: 1, recorded_at: "2026-10-21T18:00:00+00:00", revised_at: "2026-10-21T18:00:00+00:00",
  };
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    if (command === "g5_memory_page") return JSON.stringify({ ok: true, has_item: true, record });
    if (command === "g5_memory_delete") return JSON.stringify({ ok: true, deleted: true });
    if (command === "g5_memory_export") return JSON.stringify({ ok: true, exported: true });
    if (command === "g5_memory_edit") return JSON.stringify({ ok: true, record: { ...record, body: "fato corrigido", version: 2, revised_at: "2026-10-21T18:05:00+00:00" } });
    return JSON.stringify({ ok: true, record });
  });
  const page = await ipc.memoryPage("confirmed_fact", "dom_synthetic_b", 0);
  await ipc.memoryCreate("confirmed_fact", "dom_synthetic_b", record.body, record.source_ref);
  await ipc.memoryEdit("confirmed_fact", "dom_synthetic_b", record.id, "fato corrigido", 1);
  await ipc.memoryDelete("confirmed_fact", "dom_synthetic_b", record.id, 2);
  const exported = await ipc.memoryExport();
  assert.equal(page.memory_record.source_ref, "owner-note");
  assert.equal(exported.exported, true);
  assert.deepEqual(calls, [
    { command: "g5_memory_page", args: { category: "confirmed_fact", domainId: "dom_synthetic_b", offset: 0 } },
    { command: "g5_memory_create", args: { category: "confirmed_fact", domainId: "dom_synthetic_b", body: record.body, sourceRef: "owner-note" } },
    { command: "g5_memory_edit", args: { category: "confirmed_fact", domainId: "dom_synthetic_b", recordId: record.id, body: "fato corrigido", expectedRevision: 1 } },
    { command: "g5_memory_delete", args: { category: "confirmed_fact", domainId: "dom_synthetic_b", recordId: record.id, expectedRevision: 2 } },
    { command: "g5_memory_export", args: undefined },
  ]);
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, has_item: true, record: { ...record, extra: "campo" } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, has_item: true, record: { ...record, domain_id: "dom_real" } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, exported: true, path: "/arbitrario" })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, has_item: false, record })));
});

test("memória recusa categoria, domínio e revisão inválidos antes do IPC", async () => {
  const calls = [];
  const ipc = createG5Ipc(async (command) => { calls.push(command); return "{}"; });
  const id = "0123456789abcdef0123456789abcdef";
  await assert.rejects(() => ipc.memoryPage("unknown", "dom_synthetic_a", 0));
  await assert.rejects(() => ipc.memoryPage("confirmed_fact", "dom_invalid", 0));
  await assert.rejects(() => ipc.memoryCreate("confirmed_fact", "dom_invalid", "sintético", "origin"));
  await assert.rejects(() => ipc.memoryEdit("confirmed_fact", "dom_synthetic_a", id, "sintético", 0));
  await assert.rejects(() => ipc.memoryDelete("confirmed_fact", "dom_synthetic_a", id, -1));
  assert.deepEqual(calls, []);
});

test("handlers de exclusão e sessão invalidam as cópias de memória na tela", () => {
  // Structural regression only. This does not replace an interactive smoke test.
  const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  const deletion = app.slice(app.indexOf("async function deleteMemory("), app.indexOf("async function exportMemory("));
  for (const setter of ["setMemoryRecords", "setCaptures", "setSearchHits", "setOpenedOrigin", "setMemoryBody"]) {
    assert.ok(deletion.includes(setter), setter);
  }
  const captureDeletion = app.slice(app.indexOf("async function removeCapture("), app.indexOf("async function searchIdeas("));
  assert.ok(captureDeletion.includes("setMemoryRecords"));
  assert.ok(captureDeletion.includes("setMemorySelectedId"));
  const bulkDeletion = app.slice(app.indexOf("async function clearCaptures("), app.indexOf("async function refreshAutomationData("));
  assert.ok(bulkDeletion.includes('item.category !== "explicit_capture"'));
  const sessionInvalidation = app.slice(app.indexOf('if (next.snapshot.state !== "READY"'), app.indexOf("} else if (!grantIsDisplayedActive"));
  for (const setter of ["setMemoryRecords([])", "setSearchHits(null)", "setOpenedOrigin(null)", 'setMemoryBody("")']) {
    assert.ok(sessionInvalidation.includes(setter), setter);
  }
});

test("busca e abertura de captura usam comandos IPC tipados", async () => {
  const calls = [];
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    if (command === "g5_capture_search") {
      return JSON.stringify({ ok: true, captures: [] });
    }
    return JSON.stringify({
      ok: true,
      origin: {
        id: "0123456789abcdef0123456789abcdef",
        text: "reunião sintética",
        created_at: "2026-10-17T15:00:00+00:00",
        domain_id: "dom_synthetic_a",
        category: "explicit_capture",
      },
    });
  });
  const found = await ipc.searchCaptures("reuniao");
  const opened = await ipc.openCapture("0123456789abcdef0123456789abcdef");
  assert.deepEqual(found.captures, []);
  assert.equal(found.omitted, undefined);
  assert.equal(opened.origin.domain_id, "dom_synthetic_a");
  assert.equal(opened.origin.category, "explicit_capture");
  assert.equal(opened.origin.text, "reunião sintética");
  assert.deepEqual(calls, [
    { command: "g5_capture_search", args: { query: "reuniao" } },
    { command: "g5_capture_open", args: { capture_id: "0123456789abcdef0123456789abcdef" } },
  ]);
});

test("conversa grounded usa IPC fechado e descarta resposta de conversa anterior", async () => {
  const calls = [];
  const conversationId = "0123456789abcdef0123456789abcdef";
  const factId = "abcdef0123456789abcdef0123456789";
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    if (args?.question === "estoque confirmado") {
      return JSON.stringify({ ok: true, grounded_read: {
        status: "evidence", reason: "", provider_id: "fake-deterministic", cost: "unmeasured",
        text: "estoque", omitted: 0,
        sources: [{ id: factId, kind: "confirmed_fact", domain_id: "dom_synthetic_a", snippet: "estoque" }],
      } });
    }
    return JSON.stringify({ ok: true, grounded_read: {
      status: "evidence", reason: "", provider_id: "fake-deterministic", cost: "unmeasured",
      text: "prazo", omitted: 0,
      sources: [{ id: conversationId, kind: "capture", domain_id: "dom_synthetic_a", snippet: "prazo" }],
    } });
  });
  const result = await ipc.groundedRead(conversationId, "qual prazo");
  assert.equal(result.grounded_read.status, "evidence");
  assert.equal(result.grounded_read.sources[0].id, conversationId);
  const fact = await ipc.groundedRead(conversationId, "estoque confirmado");
  assert.equal(fact.grounded_read.status, "evidence");
  assert.equal(fact.grounded_read.text, "estoque");
  assert.deepEqual(fact.grounded_read.sources, [{
    id: factId, kind: "confirmed_fact", domain_id: "dom_synthetic_a", snippet: "estoque",
  }]);
  assert.deepEqual(calls, [
    { command: "g5_conversation_ask", args: { conversation_id: conversationId, question: "qual prazo" } },
    { command: "g5_conversation_ask", args: { conversation_id: conversationId, question: "estoque confirmado" } },
  ]);
  const refused = {
    status: "evidence", reason: "", provider_id: "fake-deterministic", cost: "unmeasured",
    text: "estoque", omitted: 0,
    sources: [{ id: factId, kind: "confirmed_fact", domain_id: "dom_synthetic_a", snippet: "estoque" }],
  };
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, grounded_read: { ...refused, unknown: true } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, grounded_read: {
    ...refused, sources: [{ ...refused.sources[0], kind: "tool" }],
  } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, grounded_read: {
    ...refused, sources: [{ ...refused.sources[0], domain_id: "dom_synthetic_b" }],
  } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, grounded_read: {
    ...refused, sources: [{ ...refused.sources[0], tool: "read_secret" }],
  } })));
  const gate = new ConversationRequestGate();
  const old = gate.begin("conversa-antiga");
  const current = gate.begin("conversa-atual");
  assert.equal(gate.isCurrent(old, "conversa-atual"), false);
  assert.equal(gate.isCurrent(current, "conversa-atual"), true);
  gate.invalidate();
  assert.equal(gate.isCurrent(current, "conversa-atual"), false);
});

test("abertura, cancelamento e pergunta preservam allowlists de fio em ordem fixa", async () => {
  assert.deepEqual(CONVERSATION_ASK_WIRE_FIELDS, ["session_token", "conversation_id", "question", "domain_id"]);
  assert.deepEqual(CONVERSATION_OPEN_WIRE_FIELDS, ["session_token", "domain_id", "mode"]);
  assert.deepEqual(CONVERSATION_CANCEL_WIRE_FIELDS, ["session_token", "conversation_id", "domain_id"]);
  const calls = [];
  const id = "0123456789abcdef0123456789abcdef";
  const ipc = createG5Ipc(async (command, args) => {
    calls.push({ command, args });
    return command === "g5_conversation_open"
      ? JSON.stringify({ ok: true, id, expires_at: "2099-01-01T00:00:00+00:00" })
      : JSON.stringify({ ok: true, cancelled: true });
  });
  const opened = await ipc.openConversation("resume");
  const cancelled = await ipc.cancelConversation(id);
  assert.equal(opened.id, id);
  assert.equal(opened.expires_at, "2099-01-01T00:00:00+00:00");
  assert.equal(cancelled.cancelled, true);
  assert.deepEqual(calls, [
    { command: "g5_conversation_open", args: { mode: "resume" } },
    { command: "g5_conversation_cancel", args: { conversation_id: id } },
  ]);
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, id, expires_at: "2099-01-01T00:00:00Z", extra: true })));
  await assert.rejects(ipc.groundedRead("conversa-a", "qual prazo"));
});

test("geração de documento sintético usa comando IPC fechado e valida artefato e origem", async () => {
  assert.deepEqual(SYNTHETIC_DOCUMENT_WIRE_FIELDS, ["session_token", "csrf_token"]);
  assert.deepEqual(STORAGE_ROTATE_WIRE_FIELDS, ["database_key", "generation", "operation_id", "intent"]);
  assert.deepEqual(STORAGE_ROTATE_RETIRE_WIRE_FIELDS, ["from_account"]);
  assert.deepEqual(STORAGE_ROTATE_FINALIZE_WIRE_FIELDS, ["database_key", "operation_id"]);
  assert.equal(STORAGE_ROTATE_WIRE_FIELDS.includes("extra"), false);
  const calls = [];
  const artifact = {
    id: "doc_0123456789abcdef", schema_version: 1, kind: "synthetic_document",
    title: "Resumo sintético de exemplo",
    sections: [{ index: 1, heading: "Conteúdo de teste",
      paragraphs: ["Este documento contém somente texto sintético local."], source_id: "src_exemplo_sintetico" }],
    origin: { skill_id: "generate-synthetic-document", skill_version: "1.0.0",
      manifest_sha256: "a".repeat(64), license_name: "nao-declarada-no-arquivo-local" },
    permission: { capability: "generate_synthetic_document", scope: "synthetic", principal: "owner" },
  };
  const ipc = createG5Ipc(async (command, args) => {
    calls.push([command, args]);
    return JSON.stringify({ ok: true, artifact, artifact_sha256: "a".repeat(64) });
  });
  const result = await ipc.generateSyntheticDocument();
  assert.equal(result.artifact.id, artifact.id);
  assert.equal(result.artifact_sha256, "a".repeat(64));
  assert.deepEqual(calls, [["g5_synthetic_document_generate", undefined]]);
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, artifact: { ...artifact, unknown: true } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, artifact: {
    ...artifact, permission: { ...artifact.permission, scope: "external" },
  } })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, artifact, extra: true })));
});

test("captura rejeita campo ou código desconhecido e informa omissão", () => {
  const capture = { id: "0123456789abcdef0123456789abcdef", text: "ideia", created_at: "2026-10-17T18:00:00+00:00" };
  const full = [capture, { ...capture, id: "1123456789abcdef0123456789abcdef" }, { ...capture, id: "2123456789abcdef0123456789abcdef" }];
  const parsed = parseG5CommandResult(JSON.stringify({ ok: true, captures: full, omitted: 2 }));
  assert.equal(parsed.omitted, 2);
  assert.equal(parsed.captures.length, 3);
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, captures: [capture], omitted: 2, items: [capture] })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, captures: [{ ...capture, token: "segredo" }] })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({
    ok: true,
    origin: { ...capture, domain_id: "dom_synthetic_a", code: "capture_rejected" },
  })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({
    ok: true,
    origin: { ...capture, domain_id: "dom_synthetic_b", category: "explicit_capture" },
  })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({
    ok: true,
    origin: { ...capture, domain_id: "dom_synthetic_a", category: "inferred_fact" },
  })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({
    ok: true,
    items: [capture],
  })));
  assert.throws(() => parseG5CommandResult(JSON.stringify({ ok: true, captures: [capture], omitted: 1 })));
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


test("histórico paginado usa somente comando tipado e cursor limitado", async () => {
  const calls = [];
  const ipc = createG5Ipc(async (command, args) => {
    calls.push([command, args]);
    return JSON.stringify({ ok: true, tasks: [], next_cursor: "" });
  });
  assert.deepEqual(await ipc.workflowPage(), { ok: true, tasks: [], next_cursor: "" });
  assert.deepEqual(calls, [["g5_workflow_page", { cursor: "" }]]);
  await assert.rejects(ipc.workflowPage("x".repeat(81)));
  await assert.rejects(ipc.workflowPage(`wf1|2026-02-30T00:00:00+00:00|${"a".repeat(32)}`));
  assert.equal(calls.length, 1);
});

test("página recusa extras, ordem invertida, cursor divergente e mantém fim explícito", () => {
  const task = (id) => ({ task_id: id.repeat(32), tool_id: "draft_note", state: "proposed",
    arguments_sha: "a".repeat(64), created_at: "2026-10-14T00:00:00+00:00",
    updated_at: "2026-10-14T00:00:00+00:00", risk: "low", expected_effect: "rascunho local persistido" });
  const cursor = `wf1|2026-10-14T00:00:00+00:00|${"b".repeat(32)}`;
  const response = (tasks, next_cursor = "", extra = {}) => JSON.stringify({ ok: true, tasks, next_cursor, ...extra });
  assert.equal(parseWorkflowPageResult(response([task("b")], cursor)).next_cursor, cursor);
  assert.throws(() => parseWorkflowPageResult(response([task("b")], cursor), cursor));
  assert.throws(() => parseWorkflowPageResult(response([task("a"), task("b")])));
  assert.throws(() => parseWorkflowPageResult(response([{ ...task("b"), extra: true }])));
  assert.throws(() => parseWorkflowPageResult(response([], cursor)));
  assert.throws(() => parseWorkflowPageResult(response([], "", { extra: true })));
  assert.throws(() => parseWorkflowPageResult(response([task("a")], cursor)));
  assert.deepEqual(parseWorkflowPageResult(response([]), cursor), { ok: true, tasks: [], next_cursor: "" });
});


test("fixture real da API mantém o contrato consumido pela interface", () => {
  const wire = readFileSync(new URL("../../api/fixtures/workflow_page_v1.txt", import.meta.url), "utf8");
  const fields = Object.fromEntries(wire.trimEnd().split("\n").map((line) => {
    const index = line.indexOf("="); return [line.slice(0, index), decodeURIComponent(line.slice(index + 1))];
  }));
  const page = parseWorkflowPageResult(JSON.stringify({ ok: fields.ok === "true", tasks: JSON.parse(fields.tasks_json), next_cursor: fields.next_cursor }));
  assert.equal(page.ok, true);
  assert.equal(page.tasks[0].task_id, "a".repeat(32));
  assert.equal(page.next_cursor, "");
});
