import type { Mission } from "@/lib/mission-contracts";
import { runNextStep } from "@/lib/mission-core";

export const MISSION_STORAGE_KEY = "jarvis.synthetic.missions.v1";

export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function loadMissions(storage: KeyValueStorage): Mission[] {
  try {
    const raw = storage.getItem(MISSION_STORAGE_KEY);
    if (!raw) return [];
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data)) return [];
    return data.filter((item): item is Mission =>
      Boolean(item && typeof item === "object" && (item as Mission).schema_version === 1 &&
        typeof (item as Mission).id === "string" && typeof (item as Mission).title === "string" &&
        Array.isArray((item as Mission).tasks) && Array.isArray((item as Mission).events) &&
        (item as Mission).budget?.cap === 0 && (item as Mission).budget?.spent === 0)
    );
  } catch {
    return [];
  }
}

export function saveMissions(storage: KeyValueStorage, missions: Mission[]): void {
  storage.setItem(MISSION_STORAGE_KEY, JSON.stringify(missions));
}

export function runAndSaveNextStep(storage: KeyValueStorage, missionId: string, requestKey: string, now: string): Mission | null {
  const missions = loadMissions(storage);
  const current = missions.find((item) => item.id === missionId);
  if (!current) return null;
  const next = runNextStep(current, { idempotencyKey: requestKey, now });
  saveMissions(storage, missions.map((item) => item.id === missionId ? next : item));
  return next;
}
