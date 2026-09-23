"use client";

import { useCallback, useEffect, useState } from "react";
import { fixtures } from "@/lib/demo";
import { isKnownDomainId } from "@/lib/domains";

/** Só fixtures DEMO. Não é nuvem, não sobrevive a limpar dados do site, teto de 50 capturas extras. */
export const DEMO_INBOX_STORAGE_KEY = "jarvis.demo.inbox.v1";
export const DEMO_INBOX_STORAGE_LIMIT = 50;
export const DEMO_STORAGE_LIMITS =
  "Armazenamento local do navegador, apenas dados DEMO. Não sincroniza entre aparelhos e some ao limpar os dados do site. Máximo de 50 capturas extras.";

export type DemoCapture = {
  id: string;
  domain_id: string;
  type: string;
  title: string;
  status: string;
  created_at: string;
  evidence: string;
  entity_ref?: string;
};

const CHANGE_EVENT = "jarvis-demo-inbox";

function fromFixtures(): DemoCapture[] {
  return fixtures.inbox.map((item) => ({
    id: item.id,
    domain_id: item.domain_id,
    type: item.type,
    title: item.title,
    status: item.status,
    created_at: item.created_at,
    evidence: item.evidence,
    entity_ref: item.entity_ref
  }));
}

function isCapture(value: unknown): value is DemoCapture {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<DemoCapture>;
  return typeof item.id === "string" && typeof item.title === "string" && typeof item.domain_id === "string" && isKnownDomainId(item.domain_id);
}

export function readExtraCaptures(): DemoCapture[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(DEMO_INBOX_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isCapture).slice(0, DEMO_INBOX_STORAGE_LIMIT);
  } catch {
    return [];
  }
}

export function mergeCaptures(extra = readExtraCaptures()): DemoCapture[] {
  const base = fromFixtures();
  const seen = new Set(extra.map((item) => item.id));
  return [...extra, ...base.filter((item) => !seen.has(item.id))];
}

export function appendCapture(capture: DemoCapture): DemoCapture[] {
  if (!isKnownDomainId(capture.domain_id)) {
    return mergeCaptures();
  }
  const next = [capture, ...readExtraCaptures().filter((item) => item.id !== capture.id)].slice(0, DEMO_INBOX_STORAGE_LIMIT);
  window.localStorage.setItem(DEMO_INBOX_STORAGE_KEY, JSON.stringify(next));
  window.dispatchEvent(new Event(CHANGE_EVENT));
  return mergeCaptures(next);
}

export function useDemoCaptures(): DemoCapture[] {
  const [items, setItems] = useState<DemoCapture[]>(fromFixtures);

  const sync = useCallback(() => {
    setItems(mergeCaptures());
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

  return items;
}
