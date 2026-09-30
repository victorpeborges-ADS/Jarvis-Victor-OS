import { describe, expect, it } from "vitest";
import { knowledgeOriginLabel } from "@/lib/knowledge-origin";

describe("knowledge origin labels", () => {
  it("does not present a stored kind as trusted provenance", () => {
    expect(knowledgeOriginLabel(false, "skill_derived")).toBe("Origem não verificada");
    expect(knowledgeOriginLabel(false, "selected_original")).toBe("Origem não verificada");
    expect(knowledgeOriginLabel(false, null)).toBe("Origem não verificada");
  });

  it("names an origin only after the API confirms its provenance", () => {
    expect(knowledgeOriginLabel(true, "selected_original")).toBe("Fixture sintética selecionada");
    expect(knowledgeOriginLabel(true, "skill_derived")).toBe("Derivação por execução verificada");
    expect(knowledgeOriginLabel(true, null)).toBe("Origem não verificada");
  });
});
