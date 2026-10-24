import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
import * as runtimeCommands from "../src/runtimeCommand.ts";

// Execute the real component's hooks/handlers with deferred IPC, without a DOM,
// native runtime, timers, listener or database. Existing TypeScript is reused.
const compiledApp = ts.transpileModule(readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const task = (id) => ({ task_id: id.repeat(32), tool_id: "draft_note", state: "proposed",
  arguments_sha: "a".repeat(64), created_at: "2026-10-14T00:00:00+00:00",
  updated_at: "2026-10-14T00:00:00+00:00", risk: "low", expected_effect: `resultado-${id}` });
const page = (id, more = false) => ({ ok: true, tasks: id ? [task(id)] : [],
  next_cursor: more ? `wf1|2026-10-14T00:00:00+00:00|${id.repeat(32)}` : "" });

function harness(overrides = {}) {
  let index = 0, dirty = true, tree;
  const slots = [], effects = [];
  const ipc = {
    sessionStatus: async () => ({ ok: true, session_active: true, session_expires_at: null,
      grant_active: false, grant_expires_at_epoch_us: null }),
    openConversation: async () => ({ ok: true,
      id: "0123456789abcdef0123456789abcdef", expires_at: "2026-10-22T19:00:00+00:00" }),
    listCaptures: async () => ({ ok: true, captures: [] }),
    connectorStatus: async () => ({ gmail_block: "missing_oauth_client", calendar_block: "missing_oauth_client" }),
    automationsList: async () => ({ ok: true, automations: [] }),
    workflowPage: async () => page(""),
    workflowSubmitDraft: async () => ({ ok: true }),
    closeSession: async () => ({ ok: true }),
    ...overrides,
  };
  const hooks = {
    useState(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = typeof initial === "function" ? initial() : initial;
      return [slots[slot], (value) => {
        const next = typeof value === "function" ? value(slots[slot]) : value;
        if (!Object.is(next, slots[slot])) { slots[slot] = next; dirty = true; }
      }];
    },
    useRef(initial) { const slot = index++; return slots[slot] ??= { current: initial }; },
    useEffect(effect, deps) {
      const slot = index++;
      const old = slots[slot];
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) {
        effects.push(() => { old?.cleanup?.(); slots[slot] = { deps, cleanup: effect() }; });
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const exports = {};
  vm.runInNewContext(compiledApp, { exports, console, Date, Intl, Set,
    window: { setInterval: () => 1, clearInterval: () => {} },
    require(name) {
      if (name === "react") return hooks;
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
      if (name === "./App.css") return {};
      if (name === "./runtimeCommand") return { ...runtimeCommands, createG5Ipc: () => ipc };
      if (name === "@tauri-apps/api/core") return { isTauri: () => true, invoke: async (command) => {
        if (command === "runtime_status") return JSON.stringify({ ok: true, snapshot: {
          state: "READY", runtime_instance_id: "synthetic", pid: null, started_at_unix_ms: null,
          ready_at_unix_ms: null, exit_code: null, failure_category: null }, error: null });
        if (command === "runtime_transport_status") return JSON.stringify({ state: "READY",
          runtime_instance_id: "synthetic", endpoint_type: "uds", protocol_version: "3", error_category: null });
        if (command === "runtime_local_config") return JSON.stringify({ ok: true,
          passphrase_configured: true, database_configured: true, database_mode: "override",
          api_root_configured: true, oauth_client_configured: false });
        throw new Error(`Unexpected command: ${command}`);
      } };
      throw new Error(`Unexpected import: ${name}`);
    },
  });
  function nodes(value) {
    if (Array.isArray(value)) return value.flatMap((entry) => nodes(entry));
    if (!value || typeof value !== "object") return [];
    return [value, ...nodes(value.props?.children)];
  }
  function text(value) {
    if (Array.isArray(value)) return value.map((entry) => text(entry)).join(" ");
    return value && typeof value === "object" ? text(value.props?.children) : String(value ?? "");
  }
  const find = (predicate) => { const found = nodes(tree).find(predicate); assert.ok(found); return found; };
  const button = (label) => find((node) => node.type === "button" && text(node) === label);
  async function flush() {
    for (let tries = 0; tries < 20; tries++) {
      if (dirty) { dirty = false; index = 0; tree = exports.default(); while (effects.length) effects.shift()(); }
      await new Promise(setImmediate);
      if (!dirty) return;
    }
    assert.fail("Component did not settle");
  }
  async function click(label) { const node = button(label); assert.ok(!node.props.disabled, label); node.props.onClick(); await flush(); }
  async function submitDraft() {
    for (const id of ["workflow-draft-title", "workflow-draft-body"]) {
      find((node) => node.props?.id === id).props.onChange({ currentTarget: { value: "Sintético" } });
    }
    await flush();
    find((node) => node.type === "form" && text(node).includes("Título do rascunho local"))
      .props.onSubmit({ preventDefault() {} });
    await flush();
  }
  return { flush, click, button, submitDraft, text: () => text(tree),
    hasButton: (label) => nodes(tree).some((node) => node.type === "button" && text(node) === label),
    alerts: () => nodes(tree).filter((node) => node.props?.role === "alert").map((node) => text(node)), ipc };
}

test("falha da carga inicial antiga não apaga uma atualização mais recente", async () => {
  const old = deferred();
  let calls = 0;
  const app = harness({ workflowPage: async () => ++calls === 2 ? old.promise : page(calls > 2 ? "b" : "") });
  await app.flush();
  await app.click("Aprovações");
  await app.submitDraft();
  assert.ok(app.text().includes("resultado-b"));
  old.reject(new Error("resposta antiga"));
  await app.flush();
  assert.ok(app.text().includes("resultado-b"));
});

test("falha de refresh antigo não reaparece como erro em outra geração", async () => {
  const old = deferred();
  let calls = 0;
  const app = harness({ workflowPage: async () => ++calls === 3 ? old.promise : page("") });
  await app.flush();
  await app.click("Aprovações");
  await app.submitDraft();
  await app.click("Agora");
  old.reject(new Error("falha do refresh antigo"));
  await app.flush();
  assert.deepEqual(app.alerts(), []);
});

test("página antiga não bloqueia nova travessia nem finaliza a requisição nova", async () => {
  const old = deferred(), current = deferred();
  let continuations = 0;
  const app = harness({ workflowPage: async (cursor = "") => cursor
    ? (++continuations === 1 ? old.promise : current.promise) : page("b", true) });
  await app.flush();
  await app.click("Aprovações");
  await app.click("Carregar mais tarefas");
  await app.click("Agora");
  await app.click("Aprovações");
  await app.click("Carregar mais tarefas");
  old.reject(new Error("falha de página antiga"));
  await app.flush();
  assert.equal(app.button("Carregar mais tarefas").props.disabled, true);
  current.resolve(page("a"));
  await app.flush();
  assert.ok(app.text().includes("resultado-a"));
  await app.click("Agora");
  assert.deepEqual(app.alerts(), []);
});

test("texto do histórico descreve a paginação disponível", async () => {
  const app = harness();
  await app.flush();
  await app.click("Aprovações");
  assert.ok(!app.text().includes("sem paginação nesta versão"));
});

test("conversa anuncia por leitor de tela que voz e captura estão desativadas", async () => {
  const app = harness();
  await app.flush();
  await app.click("Conversa");
  assert.ok(app.text().includes("0123456789abcdef0123456789abcdef"));
  assert.ok(app.text().includes("A entrada por voz está desativada nesta candidata."));
  assert.ok(app.text().includes("Use o campo de texto; nada está sendo capturado."));
  assert.ok(!app.hasButton("Iniciar ditado"));
});

test("fechar sessão invalida histórico e respostas antes do próximo polling", async () => {
  const old = deferred(), status = deferred(), next = deferred();
  let calls = 0, statuses = 0;
  const app = harness({ workflowPage: async () => ++calls <= 2 ? page("b", true)
    : calls === 3 ? old.promise : next.promise });
  const activeStatus = app.ipc.sessionStatus;
  app.ipc.sessionStatus = async () => ++statuses === 1 ? activeStatus() : status.promise;
  await app.flush();
  await app.click("Aprovações");
  await app.click("Missões");
  await app.click("Encerrar sessão e invalidar concessão");
  old.resolve(page("a", true));
  await app.flush();
  await app.click("Aprovações");
  assert.ok(!app.text().includes("resultado-a"));
  assert.ok(!app.text().includes("resultado-b"));
  assert.ok(!app.hasButton("Carregar mais tarefas"));
});
