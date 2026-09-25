import { describe, expect, it, vi } from "vitest";
import { createManualHandoff, FakeProvider, IntelligenceRouter } from "@/lib/intelligence-router";

const request = {
  capability: "draft" as const,
  classification: "synthetic_only" as const,
  objective: "Criar um resumo",
  minimal_context: "Três itens de teste",
  source_refs: [{ source_id: "synthetic:one", uri: null, observed_at: "2026-09-25T04:00:00Z", last_verified_at: null, valid_until: null, domain_id: "dom_synthetic_a" }],
  artifact_ids: ["artifact_demo"],
  budget_cap: 0 as const
};

describe("roteador local e handoff", () => {
  it("responde deterministicamente apenas pelo FakeProvider de custo zero", () => {
    const router = new IntelligenceRouter();
    const first = router.run(request);
    const second = router.run(request);
    expect(first).toEqual(second);
    expect(first.status).toBe("completed");
    expect(first.provider_id).toBe("fake-provider");
    expect(first.cost_cap).toBe(0);
    expect(first.text).toContain("FAKE · draft");
  });

  it("faz fallback sem enviar conteúdo privado ao provider", () => {
    const provider = new FakeProvider();
    const run = vi.spyOn(provider, "run");
    const router = new IntelligenceRouter([provider]);
    const result = router.run({ ...request, classification: "restricted" });
    expect(result.status).toBe("no_llm");
    expect(result.provider_id).toBeNull();
    expect(result.text).toBe(request.minimal_context);
    expect(run).not.toHaveBeenCalled();
  });

  it("gera envelope mínimo sem transmitir e exige confirmação fora do router", () => {
    const handoff = createManualHandoff(request, "review", "2026-09-25T04:00:00Z", ["revisão manual pendente"]);
    expect(handoff.destination).toBe("chatgpt_work");
    expect(handoff.transmission).toBe("manual_only");
    expect(handoff.source_refs).toEqual(request.source_refs);
    expect(handoff.approvals).toEqual(["revisão manual pendente"]);
  });
});
