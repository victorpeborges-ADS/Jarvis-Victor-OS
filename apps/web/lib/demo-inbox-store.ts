"use client";

import { useCallback, useEffect, useState } from "react";
import { fixtures } from "@/lib/demo";
import { parseFixtureCapture, parseLocalCapture, localCaptureIssue, type CaptureRecord } from "@/lib/validate";

/** Só fixtures DEMO. Não é nuvem, não sobrevive a limpar o site, teto de 50 capturas extras. */
export const DEMO_INBOX_STORAGE_KEY = "jarvis.demo.inbox.v1";
export const DEMO_INBOX_STORAGE_LIMIT = 50;
export const DEMO_STORAGE_LIMITS =
  "Armazenamento local do navegador, apenas dados DEMO. Não sincroniza entre aparelhos e some ao limpar os dados do site. Máximo de 50 capturas extras.";
export const EPHEMERAL_NOTICE =
  "O navegador recusou a gravação. Esta nota fica só nesta sessão e será perdida ao recarregar.";

export type DemoCapture = CaptureRecord;
export type StorageMode = "persistent" | "memory";
export type StorageFailure = "quota" | "blocked" | "unavailable" | "malformed";

export type AppendResult = {
  accepted: boolean;
  persisted: boolean;
  mode: StorageMode;
  reason?: "invalid" | "unknown-domain" | "collision" | StorageFailure;
  items: DemoCapture[];
};

const CHANGE_EVENT = "jarvis-demo-inbox";

let memoryExtras: DemoCapture[] | null = null;

function fixtureCaptures(): DemoCapture[] {
  return fixtures.inbox.flatMap((item) => {
    const parsed = parseFixtureCapture(item);
    return parsed ? [parsed] : [];
  });
}

function fixtureIds(): Set<string> {
  return new Set(fixtureCaptures().map((item) => item.id));
}

function failureKind(error: unknown): StorageFailure {
  if (error instanceof DOMException) {
    if (error.name === "QuotaExceededError" || error.code === 22) return "quota";
    if (error.name === "SecurityError") return "blocked";
  }
  return "unavailable";
}

function dedupeLocals(items: DemoCapture[]): DemoCapture[] {
  const reserved = fixtureIds();
  const seen = new Set<string>();
  const out: DemoCapture[] = [];
  for (const item of items) {
    if (reserved.has(item.id) || seen.has(item.id) || !item.id.startsWith("local_")) continue;
    seen.add(item.id);
    out.push(item);
    if (out.length >= DEMO_INBOX_STORAGE_LIMIT) break;
  }
  return out;
}

function normalizeStored(value: unknown): DemoCapture[] {
  if (!Array.isArray(value)) return [];
  const parsed = value.flatMap((item) => {
    const capture = parseLocalCapture(item);
    return capture ? [capture] : [];
  });
  return dedupeLocals(parsed);
}

function readPersistent(): { ok: true; items: DemoCapture[] } | { ok: false; reason: StorageFailure } {
  try {
    if (typeof window === "undefined" || !window.localStorage) return { ok: false, reason: "unavailable" };
    const raw = window.localStorage.getItem(DEMO_INBOX_STORAGE_KEY);
    if (!raw) return { ok: true, items: [] };
    try {
      return { ok: true, items: normalizeStored(JSON.parse(raw)) };
    } catch {
      return { ok: false, reason: "malformed" };
    }
  } catch (error) {
    return { ok: false, reason: failureKind(error) };
  }
}

function writePersistent(items: DemoCapture[]): { persisted: boolean; mode: StorageMode; reason?: StorageFailure } {
  try {
    if (typeof window === "undefined" || !window.localStorage) {
      memoryExtras = items;
      return { persisted: false, mode: "memory", reason: "unavailable" };
    }
    window.localStorage.setItem(DEMO_INBOX_STORAGE_KEY, JSON.stringify(items));
    memoryExtras = null;
    return { persisted: true, mode: "persistent" };
  } catch (error) {
    memoryExtras = items;
    return { persisted: false, mode: "memory", reason: failureKind(error) };
  }
}

export function isEphemeralSession(): boolean {
  return memoryExtras !== null;
}

export function readExtraCaptures(): DemoCapture[] {
  if (memoryExtras) return memoryExtras;
  const stored = readPersistent();
  return stored.ok ? stored.items : [];
}

export function mergeCaptures(extra = readExtraCaptures()): DemoCapture[] {
  const base = fixtureCaptures();
  const reserved = new Set(base.map((item) => item.id));
  return [...extra.filter((item) => !reserved.has(item.id)), ...base];
}

export function appendCapture(capture: CaptureRecord): AppendResult {
  const issue = localCaptureIssue(capture);
  if (issue || !parseLocalCapture(capture)) {
    return {
      accepted: false,
      persisted: false,
      mode: isEphemeralSession() ? "memory" : "persistent",
      reason: issue ?? "invalid",
      items: mergeCaptures()
    };
  }
  const parsed = parseLocalCapture(capture)!;
  if (fixtureIds().has(parsed.id)) {
    return {
      accepted: false,
      persisted: false,
      mode: isEphemeralSession() ? "memory" : "persistent",
      reason: "collision",
      items: mergeCaptures()
    };
  }
  const next = dedupeLocals([parsed, ...readExtraCaptures().filter((item) => item.id !== parsed.id)]);
  const write = writePersistent(next);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
  return { accepted: true, persisted: write.persisted, mode: write.mode, reason: write.reason, items: mergeCaptures(next) };
}

export function clearDemoCaptures(): { cleared: boolean; mode: StorageMode } {
  memoryExtras = null;
  try {
    if (typeof window === "undefined" || !window.localStorage) return { cleared: false, mode: "memory" };
    window.localStorage.removeItem(DEMO_INBOX_STORAGE_KEY);
    if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
    return { cleared: true, mode: "persistent" };
  } catch {
    return { cleared: false, mode: "memory" };
  }
}

export function resetDemoInboxStore(): void {
  memoryExtras = null;
}

export function useDemoCaptures(): { items: DemoCapture[]; ephemeral: boolean } {
  const [items, setItems] = useState<DemoCapture[]>(fixtureCaptures);
  const [ephemeral, setEphemeral] = useState(false);

  const sync = useCallback(() => {
    setItems(mergeCaptures());
    setEphemeral(isEphemeralSession());
  }, []);

  useEffect(() => {
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener(CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(CHANGE_EVENT, sync);
    };
  }, [sync]);

  return { items, ephemeral };
}
