import type { Mission } from "@/lib/mission-contracts";
import { runNextStep } from "@/lib/mission-core";
import { isMission } from "@/lib/mission-validation";

export const MISSION_STORAGE_KEY = "jarvis.synthetic.missions.v1";
export const MISSION_QUARANTINE_KEY = "jarvis.synthetic.missions.quarantine.v1";
const MAX_STORAGE_CHARS = 1024 * 1024;
const MAX_QUARANTINE_CHARS = 2 * 1024 * 1024;
const MAX_QUARANTINE_ENTRIES = 50;
const MAX_ENTRY_CHARS = 1024 * 1024;

export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface QuarantinedMissionRecord {
  quarantined_at: string;
  reason: "invalid_json" | "invalid_container" | "invalid_contract" | "storage_too_large";
  raw: string;
  count: number;
  truncated: boolean;
}

export interface MissionQuarantine {
  version: 1;
  records: QuarantinedMissionRecord[];
}

export interface MissionLoadResult {
  missions: Mission[];
  quarantinedCount: number;
  quarantineTruncated: boolean;
  recoveryError: boolean;
  pendingQuarantine: QuarantinedMissionRecord[];
}

function readQuarantine(storage: KeyValueStorage): MissionQuarantine {
  try {
    const raw = storage.getItem(MISSION_QUARANTINE_KEY);
    if (!raw || raw.length > MAX_QUARANTINE_CHARS) return { version: 1, records: [] };
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || (value as MissionQuarantine).version !== 1 || !Array.isArray((value as MissionQuarantine).records)) {
      return { version: 1, records: [] };
    }
    const records = (value as MissionQuarantine).records.filter((item) => item && typeof item === "object" &&
      typeof item.raw === "string" && typeof item.quarantined_at === "string" && typeof item.truncated === "boolean" &&
      ["invalid_json", "invalid_container", "invalid_contract", "storage_too_large"].includes(item.reason))
      .map((item) => ({ ...item, count: Number.isSafeInteger(item.count) && item.count > 0 ? item.count : 1 }));
    return { version: 1, records };
  } catch {
    return { version: 1, records: [] };
  }
}

function addToQuarantine(storage: KeyValueStorage, records: Array<{ raw: string; reason: QuarantinedMissionRecord["reason"]; count?: number }>): boolean {
  const prior = readQuarantine(storage).records;
  const timestamp = new Date().toISOString();
  const incoming = records.map((record): QuarantinedMissionRecord => ({
    quarantined_at: timestamp,
    reason: record.reason,
    raw: record.raw,
    count: record.count ?? 1,
    truncated: false
  }));
  const combined = [...prior, ...incoming];
  const serialized = JSON.stringify({ version: 1, records: combined });
  if (combined.length > MAX_QUARANTINE_ENTRIES || incoming.some((record) => record.raw.length > MAX_ENTRY_CHARS) || serialized.length > MAX_QUARANTINE_CHARS) return false;
  try {
    storage.setItem(MISSION_QUARANTINE_KEY, serialized);
    return true;
  } catch {
    return false;
  }
}

export function loadMissionsWithRecovery(storage: KeyValueStorage): MissionLoadResult {
  const emptyResult = (missions: Mission[], recoveryError = false): MissionLoadResult => {
    const existing = readQuarantine(storage).records;
    return {
      missions,
      quarantinedCount: existing.reduce((total, record) => total + record.count, 0),
      quarantineTruncated: existing.some((item) => item.truncated),
      recoveryError,
      pendingQuarantine: []
    };
  };
  let raw: string | null;
  try {
    raw = storage.getItem(MISSION_STORAGE_KEY);
  } catch {
    return emptyResult([], true);
  }
  if (raw === null || raw === "") return emptyResult([]);
  if (raw.length > MAX_STORAGE_CHARS) {
    const saved = addToQuarantine(storage, [{ raw, reason: "storage_too_large" }]);
    let cleared = false;
    if (saved) {
      try { storage.setItem(MISSION_STORAGE_KEY, "[]"); cleared = true; } catch { /* keep the original if storage is full */ }
    }
    const result = emptyResult([], !saved || !cleared);
    if (!saved) {
      result.quarantinedCount += 1;
      result.quarantineTruncated = true;
      result.pendingQuarantine = [{ quarantined_at: new Date().toISOString(), reason: "storage_too_large", raw, count: 1, truncated: false }];
    }
    return result;
  }

  let data: unknown;
  try { data = JSON.parse(raw); }
  catch {
    const saved = addToQuarantine(storage, [{ raw, reason: "invalid_json" }]);
    let cleared = false;
    if (saved) {
      try { storage.setItem(MISSION_STORAGE_KEY, "[]"); cleared = true; } catch { /* keep the original if storage is full */ }
    }
    const result = emptyResult([], !saved || !cleared);
    if (!saved) {
      result.quarantinedCount += 1;
      result.quarantineTruncated = true;
      result.pendingQuarantine = [{ quarantined_at: new Date().toISOString(), reason: "invalid_json", raw, count: 1, truncated: false }];
    }
    return result;
  }
  if (!Array.isArray(data)) {
    const saved = addToQuarantine(storage, [{ raw, reason: "invalid_container" }]);
    let cleared = false;
    if (saved) {
      try { storage.setItem(MISSION_STORAGE_KEY, "[]"); cleared = true; } catch { /* keep the original if storage is full */ }
    }
    const result = emptyResult([], !saved || !cleared);
    if (!saved) {
      result.quarantinedCount += 1;
      result.quarantineTruncated = true;
      result.pendingQuarantine = [{ quarantined_at: new Date().toISOString(), reason: "invalid_container", raw, count: 1, truncated: false }];
    }
    return result;
  }

  const missions: Mission[] = [];
  const invalid: Array<{ raw: string; reason: QuarantinedMissionRecord["reason"] }> = [];
  for (const item of data) {
    if (isMission(item)) missions.push(item);
    else invalid.push({ raw: JSON.stringify(item), reason: "invalid_contract" });
  }
  let recoveryError = false;
  let pendingQuarantine: QuarantinedMissionRecord[] = [];
  if (invalid.length) {
    const saved = addToQuarantine(storage, [{ raw: JSON.stringify(invalid.map((item) => item.raw)), reason: "invalid_contract", count: invalid.length }]);
    recoveryError = !saved;
    if (!recoveryError) {
      try { storage.setItem(MISSION_STORAGE_KEY, JSON.stringify(missions)); }
      catch { recoveryError = true; }
    }
    if (!saved) pendingQuarantine = [{ quarantined_at: new Date().toISOString(), reason: "invalid_contract", raw, count: invalid.length, truncated: false }];
  }
  const quarantine = readQuarantine(storage);
  return {
    missions,
    quarantinedCount: quarantine.records.reduce((total, record) => total + record.count, 0) + pendingQuarantine.reduce((total, record) => total + record.count, 0),
    quarantineTruncated: quarantine.records.some((item) => item.truncated),
    recoveryError,
    pendingQuarantine
  };
}

export function loadMissions(storage: KeyValueStorage): Mission[] {
  return loadMissionsWithRecovery(storage).missions;
}

export function getMissionQuarantine(storage: KeyValueStorage): MissionQuarantine {
  return readQuarantine(storage);
}

export function clearMissionQuarantine(storage: KeyValueStorage): void {
  storage.removeItem(MISSION_QUARANTINE_KEY);
}

export function saveMissions(storage: KeyValueStorage, missions: Mission[]): void {
  if (!Array.isArray(missions) || missions.some((mission) => !isMission(mission))) {
    throw new TypeError("Apenas missões que atendem ao contrato v1 podem ser salvas.");
  }
  storage.setItem(MISSION_STORAGE_KEY, JSON.stringify(missions));
}

export function runAndSaveNextStep(storage: KeyValueStorage, missionId: string, requestKey: string, now: string): Mission | null {
  const loaded = loadMissionsWithRecovery(storage);
  if (loaded.recoveryError) return null;
  const missions = loaded.missions;
  const current = missions.find((item) => item.id === missionId);
  if (!current) return null;
  const next = runNextStep(current, { idempotencyKey: requestKey, now });
  saveMissions(storage, missions.map((item) => item.id === missionId ? next : item));
  return next;
}
