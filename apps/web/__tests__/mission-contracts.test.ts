import Ajv2020 from "ajv/dist/2020";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Mission } from "@/lib/mission-contracts";

const root = resolve(process.cwd(), "../..");
const schema = JSON.parse(readFileSync(resolve(root, "contracts/jarvis.missions.v1.schema.json"), "utf8"));
const examples = JSON.parse(readFileSync(resolve(root, "contracts/jarvis.missions.v1.examples.json"), "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: false });
ajv.addFormat("date-time", { type: "string", validate: (value: string) => /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) });
ajv.addSchema(schema);

describe("contratos versionados Mission v1", () => {
  it("aceita os mesmos exemplos compartilhados validados pela API", () => {
    for (const [name, example] of Object.entries(examples)) {
      const validate = ajv.compile({ $ref: `${schema.$id}#/$defs/${name}` });
      expect(validate(example), `${name}: ${JSON.stringify(validate.errors)}`).toBe(true);
    }
    const mission: Mission = examples.Mission;
    expect(mission.budget.cap).toBe(0);
  });

  it("recusa status desconhecido, orçamento pago e timestamp sem fuso", () => {
    const validate = ajv.compile({ $ref: `${schema.$id}#/$defs/Mission` });
    for (const mutation of [
      (value: any) => { value.status = "executed"; },
      (value: any) => { value.budget.cap = 10; },
      (value: any) => { value.created_at = "2026-09-25T01:30:00"; },
    ]) {
      const value = structuredClone(examples.Mission);
      mutation(value);
      expect(validate(value)).toBe(false);
    }
  });
});
