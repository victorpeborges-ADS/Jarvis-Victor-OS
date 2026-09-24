import { fixtures } from "@/lib/demo";
import { eventsForDomain, countForDomain, isKnownDomainId, partitionByDomain, recordsForDomain } from "@/lib/domains";
import { appendCapture, mergeCaptures, readExtraCaptures, resetDemoInboxStore } from "@/lib/demo-inbox-store";
import { newLocalCaptureId } from "@/lib/validate";

describe("Isolamento por domain_id", () => {
  const medsynMention = fixtures.events.find((event) => event.id === "evt_006");

  it("evento MedSyn que cita CRIVO no título permanece em MedSyn", () => {
    expect(medsynMention?.title).toMatch(/CRIVO/);
    expect(medsynMention?.domain_id).toBe("dom_medsyn");
    expect(recordsForDomain(fixtures.events, "dom_medsyn").map((event) => event.id)).toContain("evt_006");
    expect(recordsForDomain(fixtures.events, "dom_crivo").map((event) => event.id)).not.toContain("evt_006");
  });

  it("isola os oito domínios sem usar título ou sensibilidade", () => {
    expect(fixtures.domains).toHaveLength(8);
    for (const domain of fixtures.domains) {
      const rows = recordsForDomain(fixtures.events, domain.id);
      expect(rows.every((event) => event.domain_id === domain.id)).toBe(true);
      expect(rows.some((event) => event.domain_id !== domain.id)).toBe(false);
    }
    const crivoEvents = eventsForDomain(fixtures.events, "dom_crivo");
    expect(crivoEvents.some((event) => /medsyn/i.test(event.title) && event.domain_id !== "dom_crivo")).toBe(false);
  });

  it("domínio ausente ou desconhecido não lança e não vaza para filtros", () => {
    expect(() => recordsForDomain([null, undefined, "texto", 7] as unknown[], "dom_medsyn")).not.toThrow();
    expect(recordsForDomain([null, undefined, "texto", 7] as unknown[], "dom_medsyn")).toEqual([]);
    expect(() => partitionByDomain([null, undefined, "texto", 7] as unknown[])).not.toThrow();
    expect(() => recordsForDomain(fixtures.events, "dom_fantasma")).not.toThrow();
    expect(recordsForDomain(fixtures.events, "dom_fantasma")).toEqual([]);
    expect(recordsForDomain(fixtures.events, "")).toEqual([]);
    const { unassigned, assigned } = partitionByDomain(fixtures.events);
    expect(unassigned.map((event) => event.id).sort()).toEqual(["evt_005", "evt_011", "evt_012"]);
    expect(assigned.some((event) => !isKnownDomainId(event.domain_id))).toBe(false);
    for (const domain of fixtures.domains) {
      expect(recordsForDomain(unassigned, domain.id)).toEqual([]);
    }
  });

  it("contagem de CRIVO usa só o identificador, não a palavra no título MedSyn", () => {
    expect(countForDomain("dom_crivo")).toBe(1);
    expect(countForDomain("dom_medsyn")).toBe(3);
  });
});

describe("Persistência DEMO do Inbox", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetDemoInboxStore();
  });

  it("grava captura com id local e recusa domínio desconhecido sem exceção", () => {
    const id = newLocalCaptureId();
    const saved = appendCapture({
      id,
      domain_id: "dom_crivo",
      type: "nota",
      title: `Nota ${id}`,
      status: "classified",
      created_at: "2026-09-23T10:00:00-03:00",
      evidence: "local"
    });
    expect(saved.accepted).toBe(true);
    expect(saved.persisted).toBe(true);
    expect(saved.items.find((item) => item.id === id)?.domain_id).toBe("dom_crivo");

    const rejected = appendCapture({
      id: newLocalCaptureId(),
      domain_id: "dom_fantasma",
      type: "nota",
      title: "não deve entrar",
      status: "classified",
      created_at: "2026-09-23T10:00:00-03:00",
      evidence: "local"
    });
    expect(rejected.accepted).toBe(false);
    expect(rejected.reason).toBe("unknown-domain");
    expect(readExtraCaptures().some((item) => item.domain_id === "dom_fantasma")).toBe(false);
    expect(mergeCaptures().some((item) => item.domain_id === "dom_fantasma")).toBe(false);
  });
});
