import { describe, expect, it } from "vitest";
import { createMission, cancelMission, failMissionTask, retryMissionTask, runNextStep } from "@/lib/mission-core";
import { clearMissionQuarantine, getMissionQuarantine, loadMissions, loadMissionsWithRecovery, MISSION_QUARANTINE_KEY, MISSION_STORAGE_KEY, runAndSaveNextStep, saveMissions } from "@/lib/mission-store";
import type { Mission } from "@/lib/mission-contracts";
import { compareClientFilteredSources, SYNTHETIC_SKILLS } from "@/lib/skill-catalog";

const now = "2026-09-25T04:00:00Z";
function makeMission(): Mission { return createMission("Relatório fictício", "dom_synthetic_a", { id: "mission_test", now }); }

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
  removeItem(key: string) { this.data.delete(key); }
}

describe("Central sintética de Missões", () => {
  it("conclui etapas em ordem e cria artefatos com origem e versão de skill", () => {
    let mission = makeMission();
    mission = runNextStep(mission, { now });
    expect(mission.tasks[0].status).toBe("done");
    mission = runNextStep(mission, { now });
    expect(mission.tasks[1].status).toBe("done");
    expect(mission.artifacts.some((artifact) => artifact.kind === "context_bundle")).toBe(true);
    mission = runNextStep(mission, { now });
    expect(mission.status).toBe("done");
    expect(mission.artifacts.some((artifact) => artifact.kind === "report" && artifact.source_refs.length > 0 && artifact.skill_version === "1.0.0")).toBe(true);
    expect(mission.budget).toEqual({ cap: 0, spent: 0 });
  });

  it("não inicia dependência pendente e registra missão bloqueada", () => {
    const mission = makeMission();
    const invalid = { ...mission, tasks: mission.tasks.map((task) => task.id === "task_capture" ? { ...task, status: "failed" as const } : task) };
    const blocked = runNextStep(invalid, { now });
    expect(blocked.status).toBe("blocked");
    expect(blocked.tasks.find((task) => task.id === "task_context")?.status).toBe("planned");
  });

  it("registra falha e prepara retry com tentativa e chave novas", () => {
    const failed = failMissionTask(makeMission(), "task_capture", "falha sintética", { now });
    const retried = retryMissionTask(failed, "task_capture", { now });
    expect(retried.tasks[0].status).toBe("planned");
    expect(retried.tasks[0].attempt).toBe(2);
    expect(retried.tasks[0].idempotency_key).not.toBe(failed.tasks[0].idempotency_key);
    expect(retried.events.some((item) => item.type === "task_retried")).toBe(true);
  });

  it("cancela etapas abertas e não altera missão concluída", () => {
    const cancelled = cancelMission(makeMission(), { now });
    expect(cancelled.status).toBe("cancelled");
    expect(cancelled.tasks.every((task) => task.status === "cancelled")).toBe(true);
    const done = { ...makeMission(), status: "done" as const };
    expect(cancelMission(done, { now })).toBe(done);
  });

  it("recupera após reload e serializa comandos locais repetidos por chave", async () => {
    const storage = new MemoryStorage();
    saveMissions(storage, [makeMission()]);
    expect(loadMissions(storage)[0].id).toBe("mission_test");
    const [first, duplicate] = await Promise.all([
      Promise.resolve(runAndSaveNextStep(storage, "mission_test", "request-1", now)),
      Promise.resolve(runAndSaveNextStep(storage, "mission_test", "request-1", now))
    ]);
    expect(first?.tasks[0].status).toBe("done");
    expect(duplicate?.events.filter((item) => item.type === "task_completed")).toHaveLength(1);
    expect(loadMissions(storage)[0].events.filter((item) => item.type === "task_completed")).toHaveLength(1);
    expect(storage.getItem(MISSION_STORAGE_KEY)).not.toBeNull();
  });

  it("preserva atualização serial de duas etapas locais", async () => {
    const storage = new MemoryStorage();
    saveMissions(storage, [makeMission()]);
    await Promise.all([
      Promise.resolve(runAndSaveNextStep(storage, "mission_test", "request-capture", now)),
      Promise.resolve(runAndSaveNextStep(storage, "mission_test", "request-context", now))
    ]);
    const saved = loadMissions(storage)[0];
    expect(saved.tasks.slice(0, 2).every((task) => task.status === "done")).toBe(true);
  });

  it("valida cada missão recuperada, põe registros inválidos em quarentena e mantém missões válidas", () => {
    const storage = new MemoryStorage();
    const invalid = { ...makeMission(), tasks: [{ id: 17 }] };
    storage.setItem(MISSION_STORAGE_KEY, JSON.stringify([makeMission(), invalid]));

    const recovered = loadMissionsWithRecovery(storage);
    expect(recovered.missions.map((mission) => mission.id)).toEqual(["mission_test"]);
    expect(recovered.quarantinedCount).toBe(1);
    expect(recovered.recoveryError).toBe(false);
    expect(JSON.parse(storage.getItem(MISSION_STORAGE_KEY) ?? "null")).toHaveLength(1);
    expect(JSON.parse(JSON.parse(storage.getItem(MISSION_QUARANTINE_KEY) ?? "null").records[0].raw).join("\n")).toContain('"id":17');
    expect(() => saveMissions(storage, [invalid as unknown as Mission])).toThrow(TypeError);
    clearMissionQuarantine(storage);
    expect(getMissionQuarantine(storage).records).toEqual([]);
  });

  it("isola JSON inválido sem quebrar a recuperação da interface", () => {
    const storage = new MemoryStorage();
    storage.setItem(MISSION_STORAGE_KEY, "[{broken-json");
    const recovered = loadMissionsWithRecovery(storage);
    expect(recovered.missions).toEqual([]);
    expect(recovered.quarantinedCount).toBe(1);
    expect(getMissionQuarantine(storage).records[0].reason).toBe("invalid_json");
  });

  it("preserva a origem e bloqueia mutações se a quarentena não puder ser gravada", () => {
    class QuarantineWriteFailure extends MemoryStorage {
      setItem(key: string, value: string) {
        if (key === MISSION_QUARANTINE_KEY) throw new Error("quota sintética excedida");
        super.setItem(key, value);
      }
    }
    const storage = new QuarantineWriteFailure();
    const invalid = { ...makeMission(), tasks: [{ id: 17 }] };
    const raw = JSON.stringify([makeMission(), invalid]);
    storage.setItem(MISSION_STORAGE_KEY, raw);

    const recovered = loadMissionsWithRecovery(storage);
    expect(recovered.recoveryError).toBe(true);
    expect(recovered.missions.map((mission) => mission.id)).toEqual(["mission_test"]);
    expect(recovered.pendingQuarantine[0].raw).toBe(raw);
    expect(storage.getItem(MISSION_STORAGE_KEY)).toBe(raw);
    expect(runAndSaveNextStep(storage, "mission_test", "blocked-by-recovery", now)).toBeNull();
    expect(storage.getItem(MISSION_STORAGE_KEY)).toBe(raw);
  });

  it("pausa mutações se a quarentena foi salva mas a chave original não pôde ser limpa", () => {
    class MainWriteFailure extends MemoryStorage {
      setItem(key: string, value: string) {
        if (key === MISSION_STORAGE_KEY && value === "[]") throw new Error("quota sintética excedida");
        super.setItem(key, value);
      }
    }
    const storage = new MainWriteFailure();
    const raw = "[{broken-json";
    storage.setItem(MISSION_STORAGE_KEY, raw);

    const recovered = loadMissionsWithRecovery(storage);
    expect(recovered.recoveryError).toBe(true);
    expect(recovered.pendingQuarantine).toEqual([]);
    expect(storage.getItem(MISSION_STORAGE_KEY)).toBe(raw);
    expect(getMissionQuarantine(storage).records[0].raw).toBe(raw);
    expect(runAndSaveNextStep(storage, "mission_test", "blocked-by-main-write", now)).toBeNull();
  });

  it("não sobrescreve dados quando o limite da quarentena é atingido", () => {
    const storage = new MemoryStorage();
    const records = Array.from({ length: 50 }, (_, index) => ({
      quarantined_at: now, reason: "invalid_contract", raw: `registro-${index}`, count: 1, truncated: false
    }));
    storage.setItem(MISSION_QUARANTINE_KEY, JSON.stringify({ version: 1, records }));
    const raw = JSON.stringify([{ invalid: true }]);
    storage.setItem(MISSION_STORAGE_KEY, raw);

    const recovered = loadMissionsWithRecovery(storage);
    expect(recovered.recoveryError).toBe(true);
    expect(recovered.pendingQuarantine[0].raw).toBe(raw);
    expect(storage.getItem(MISSION_STORAGE_KEY)).toBe(raw);
    expect(getMissionQuarantine(storage).records).toHaveLength(50);
  });

  it("mantém skills determinísticas, sintéticas e com custo zero", () => {
    expect(SYNTHETIC_SKILLS.map((skill) => skill.id)).toEqual(["capture-and-classify", "build-context", "draft-evidenced-report", "compare-sources"]);
    expect(SYNTHETIC_SKILLS.every((skill) => skill.cost_cap === 0 && skill.privacy === "synthetic_only" && skill.retries <= 3)).toBe(true);
    expect(SYNTHETIC_SKILLS.flatMap((skill) => skill.tool_allowlist).some((tool) => (tool as string).includes("shell"))).toBe(false);
  });

  it("testa a comparação sintética como helper sem chamá-la como autorização", () => {
    const sources = [
      { source_id: "synthetic:one", content: "mesmo", observed_at: now, domain_id: "dom_synthetic_a" },
      { source_id: "synthetic:two", content: "mesmo", observed_at: now, domain_id: "dom_synthetic_a" }
    ];
    expect(compareClientFilteredSources(sources, now, "same").content).toContain("idênticos");
    expect(compareClientFilteredSources(sources.map((source, index) => index === 1 ? { ...source, content: `${source.content}!` } : source), now, "different").content).toContain("diferem");
  });
});
