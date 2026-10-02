import assert from "node:assert/strict";
import test from "node:test";
import { executeRuntimeCommand } from "../src/runtimeCommand.ts";

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
