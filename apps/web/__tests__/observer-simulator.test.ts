import { describe, expect, it } from "vitest";
import { FakeWorkflowAdapter, type SyntheticChange } from "@/lib/observer-simulator";
import type { NotificationPolicy } from "@/lib/mission-contracts";

const changes: SyntheticChange[] = [
  { id: "change_allowed", source_id: "synthetic:calendar", domain_id: "dom_synthetic_a", severity: "normal", summary: "Evento de teste", created_at: "2026-09-25T04:00:00Z" },
  { id: "change_denied", source_id: "synthetic:private", domain_id: "dom_synthetic_a", severity: "critical", summary: "não incluir", created_at: "2026-09-25T04:00:00Z" },
  { id: "change_wrong_domain", source_id: "synthetic:other", domain_id: "dom_synthetic_b", severity: "critical", summary: "fora do escopo", created_at: "2026-09-25T04:00:00Z" }
];
const grants = new Set(["synthetic:calendar", "synthetic:other"]);
const domains = new Set(["dom_synthetic_a"]);
const policy: NotificationPolicy = { enabled: true, channels: ["in_app"], interruptions: "critical_only", quiet_hours: null };

describe("observadores e workflow fake", () => {
  it("filtra grants antes do domínio e só gera uma saída local read-only", () => {
    const result = new FakeWorkflowAdapter().run(changes, policy, grants, domains, "2026-09-25T04:00:00Z");
    expect(result.mode).toBe("read_only");
    expect(result.included.map((item) => item.id)).toEqual(["change_allowed"]);
    expect(result.omitted.map((item) => item.reason)).toEqual(["grant_denied", "wrong_domain"]);
    expect(result.side_effects).toEqual([]);
    expect(result.notification).toBe("suppressed");
  });

  it("respeita horário silencioso, interrupções e política desativada", () => {
    const critical: SyntheticChange[] = [{ ...changes[0], severity: "critical" }];
    const inQuietHours: NotificationPolicy = { ...policy, interruptions: "all", quiet_hours: { start: "21:00", end: "07:00", timezone: "UTC" } };
    expect(new FakeWorkflowAdapter().run(critical, inQuietHours, grants, domains, "2026-09-25T23:00:00Z").notification).toBe("suppressed");
    const disabled = new FakeWorkflowAdapter().run(critical, { ...policy, enabled: false, interruptions: "all" }, grants, domains, "2026-09-25T12:00:00Z");
    expect(disabled.notification).toBe("suppressed");
    expect(disabled.omitted[0].reason).toBe("disabled");
  });
});
