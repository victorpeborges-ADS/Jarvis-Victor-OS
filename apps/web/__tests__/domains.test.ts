import { fixtures } from "@/lib/demo";
import { countForDomain, isKnownDomainId, partitionByDomain, recordsForDomain } from "@/lib/domains";
import { appendCapture, mergeCaptures, readExtraCaptures, DEMO_INBOX_STORAGE_KEY } from "@/lib/demo-inbox-store";

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
    const crivoEvents = recordsForDomain(fixtures.events, "dom_crivo");
    expect(crivoEvents.some((event) => /medsyn/i.test(event.title) && event.domain_id !== "dom_crivo")).toBe(false);
  });

  it("domínio ausente ou desconhecido não lança e não vaza para filtros", () => {
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
  });

  it("grava captura com id estável e recusa domínio desconhecido sem exceção", () => {
    const saved = appendCapture({
      id: "inb_trace_1",
      domain_id: "dom_crivo",
      type: "nota",
      title: "Nota inb_trace_1",
      status: "classified",
      created_at: "2026-09-23T10:00:00-03:00",
      evidence: "local"
    });
    expect(saved.find((item) => item.id === "inb_trace_1")?.domain_id).toBe("dom_crivo");
    expect(JSON.parse(window.localStorage.getItem(DEMO_INBOX_STORAGE_KEY) ?? "[]")[0].id).toBe("inb_trace_1");

    expect(() =>
      appendCapture({
        id: "inb_bad",
        domain_id: "dom_fantasma",
        type: "nota",
        title: "não deve entrar",
        status: "classified",
        created_at: "2026-09-23T10:00:00-03:00",
        evidence: "local"
      })
    ).not.toThrow();
    expect(readExtraCaptures().some((item) => item.id === "inb_bad")).toBe(false);
    expect(mergeCaptures().some((item) => item.domain_id === "dom_fantasma")).toBe(false);
  });
});
