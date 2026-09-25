import { describe, expect, it } from "vitest";
import { createMission, cancelMission, failMissionTask, retryMissionTask, runNextStep } from "@/lib/mission-core";
import { loadMissions, MISSION_STORAGE_KEY, runAndSaveNextStep, saveMissions } from "@/lib/mission-store";
import type { Mission } from "@/lib/mission-contracts";
import { SYNTHETIC_SKILLS } from "@/lib/skill-catalog";

const now = "2026-09-25T04:00:00Z";
function makeMission(): Mission { return createMission("Relatório fictício", "dom_synthetic_a", { id: "mission_test", now }); }

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(key: string) { return this.data.get(key) ?? null; }
  setItem(key: string, value: string) { this.data.set(key, value); }
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

  it("mantém skills determinísticas, sintéticas e com custo zero", () => {
    expect(SYNTHETIC_SKILLS.map((skill) => skill.id)).toEqual(["capture-and-classify", "build-context", "draft-evidenced-report", "compare-sources"]);
    expect(SYNTHETIC_SKILLS.every((skill) => skill.cost_cap === 0 && skill.privacy === "synthetic_only" && skill.retries <= 3)).toBe(true);
    expect(SYNTHETIC_SKILLS.flatMap((skill) => skill.tool_allowlist).some((tool) => (tool as string).includes("shell"))).toBe(false);
  });
});
