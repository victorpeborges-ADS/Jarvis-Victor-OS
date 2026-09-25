import { describe, expect, it } from "vitest";
import { planMissionImport } from "@/lib/mission-import";
import type { Mission } from "@/lib/mission-contracts";

const mission = {
  schema_version: 1,
  id: "mission_demo",
  title: "Revisão sintética",
  description: "Missão para validar contratos",
  status: "planned",
  domain_id: "dom_synthetic_a",
  tasks: [{ id: "task_review", title: "Revisar itens", status: "planned", depends_on: [], attempt: 1, idempotency_key: "mission-review-v1", updated_at: "2026-09-25T01:30:00-03:00", failure_reason: null }],
  checkpoints: [],
  events: [{ id: "event_created", type: "mission_created", message: "Missão sintética criada", task_id: null, created_at: "2026-09-25T01:30:00-03:00", idempotency_key: "mission-created-v1" }],
  artifacts: [],
  budget: { cap: 0, spent: 0 },
  created_at: "2026-09-25T01:30:00-03:00",
  updated_at: "2026-09-25T01:30:00-03:00"
} as Mission;

describe("prévia de importação", () => {
  it("quarentena JSON inválido e não duplica identificador", () => {
    const plan = planMissionImport([mission, { title: "<script>" }, mission, { ...mission, id: "mission_other", domain_id: null }]);
    expect(plan.accepted.map((item) => item.id)).toEqual(["mission_demo"]);
    expect(plan.quarantined.map((item) => item.reason)).toEqual([
      "contrato inválido",
      "identificador repetido",
      "domínio ausente; DEMO e API não são misturados"
    ]);
  });
});
