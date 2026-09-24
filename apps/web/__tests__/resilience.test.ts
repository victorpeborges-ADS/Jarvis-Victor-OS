import { fixtures } from "@/lib/demo";
import { eventsForDomain, partitionByDomain } from "@/lib/domains";
import {
  appendCapture,
  clearDemoCaptures,
  DEMO_INBOX_STORAGE_KEY,
  DEMO_INBOX_STORAGE_LIMIT,
  mergeCaptures,
  readExtraCaptures,
  resetDemoInboxStore
} from "@/lib/demo-inbox-store";
import { documentMatchesSchema, newLocalCaptureId, type CaptureRecord } from "@/lib/validate";

const capture = (id = newLocalCaptureId(), domain_id = "dom_crivo"): CaptureRecord => ({
  id,
  domain_id,
  type: "nota",
  title: `Nota ${id}`,
  status: "classified",
  created_at: "2026-09-23T10:00:00-03:00",
  evidence: "DEMO"
});

describe("regressão da auditoria 1.3", () => {
  beforeEach(() => {
    localStorage.clear();
    resetDemoInboxStore();
  });

  it("a fixture canônica obedece ao schema", () => {
    expect(documentMatchesSchema(fixtures)).toBe(true);
  });

  it("evento MedSyn que cita CRIVO não entra no filtro CRIVO", () => {
    expect(eventsForDomain(fixtures.events, "dom_crivo").some((event) => event.id === "evt_006")).toBe(false);
    expect(eventsForDomain(fixtures.events, "dom_medsyn").some((event) => event.id === "evt_006")).toBe(true);
  });

  it("evento incompleto não aparece em domínio algum", () => {
    const broken = [{ id: "evt_x", domain_id: "dom_medsyn", title: "cita CRIVO" }];
    expect(eventsForDomain(broken, "dom_medsyn")).toEqual([]);
    expect(partitionByDomain(broken).assigned).toEqual([]);
    expect(partitionByDomain(broken).unassigned).toEqual([]);
  });

  it("deduplica e preserva a fixture quando o id colide", () => {
    const id = newLocalCaptureId();
    appendCapture(capture(id));
    appendCapture({ ...capture(id), title: "segunda versão" });
    expect(readExtraCaptures().filter((item) => item.id === id)).toHaveLength(1);

    localStorage.setItem(
      DEMO_INBOX_STORAGE_KEY,
      JSON.stringify([capture(id), { ...capture(id), title: "cópia" }, { ...capture("inb_001"), id: "inb_001", domain_id: "dom_medsyn", title: "fixture adulterada" }])
    );
    resetDemoInboxStore();
    expect(readExtraCaptures().filter((item) => item.id === id)).toHaveLength(1);
    expect(mergeCaptures().find((item) => item.id === "inb_001")?.domain_id).toBe("dom_crivo");
    expect(mergeCaptures().filter((item) => item.id === "inb_001")).toHaveLength(1);
  });

  it("rejeita captura incompleta", () => {
    localStorage.setItem(DEMO_INBOX_STORAGE_KEY, JSON.stringify([{ id: newLocalCaptureId(), title: "sem contrato", domain_id: "dom_crivo" }]));
    expect(readExtraCaptures()).toEqual([]);
  });

  it("limita extras a 50", () => {
    for (let index = 0; index < DEMO_INBOX_STORAGE_LIMIT + 3; index += 1) appendCapture(capture());
    expect(readExtraCaptures()).toHaveLength(DEMO_INBOX_STORAGE_LIMIT);
  });

  it("JSON inválido não derruba a leitura", () => {
    localStorage.setItem(DEMO_INBOX_STORAGE_KEY, "{não-json");
    expect(readExtraCaptures()).toEqual([]);
    expect(mergeCaptures().some((item) => item.id === "inb_001")).toBe(true);
  });

  it("quota e storage bloqueado não anunciam persistência", () => {
    const original = localStorage.setItem.bind(localStorage);
    try {
      localStorage.setItem = () => {
        throw new DOMException("quota", "QuotaExceededError");
      };
      const quota = appendCapture(capture());
      expect(quota.accepted).toBe(true);
      expect(quota.persisted).toBe(false);
      expect(quota.mode).toBe("memory");
      expect(quota.reason).toBe("quota");
    } finally {
      localStorage.setItem = original;
      resetDemoInboxStore();
    }

    try {
      localStorage.setItem = () => {
        throw new DOMException("blocked", "SecurityError");
      };
      const blocked = appendCapture(capture());
      expect(blocked.persisted).toBe(false);
      expect(blocked.reason).toBe("blocked");
      expect(() => appendCapture(capture())).not.toThrow();
    } finally {
      localStorage.setItem = original;
      resetDemoInboxStore();
    }
  });

  it("limpeza remove extras e o reload lógico volta às fixtures", () => {
    const id = newLocalCaptureId();
    appendCapture(capture(id));
    expect(clearDemoCaptures().cleared).toBe(true);
    resetDemoInboxStore();
    expect(readExtraCaptures().some((item) => item.id === id)).toBe(false);
    expect(mergeCaptures().some((item) => item.id === "inb_001")).toBe(true);
  });
});
