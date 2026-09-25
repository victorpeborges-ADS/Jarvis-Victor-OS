export const OUTBOX_KEY = "jarvis.mobile.synthetic.outbox.v1";
export const MAX_OUTBOX_ITEMS = 20;

export interface SyntheticCapture {
  id: string;
  text: string;
  created_at: string;
  synthetic: true;
}

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function loadSyntheticOutbox(storage: StorageLike): SyntheticCapture[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(OUTBOX_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value): value is SyntheticCapture =>
      Boolean(value && typeof value === "object" &&
        typeof value.id === "string" && value.id.length <= 100 &&
        typeof value.text === "string" && value.text.length <= 500 &&
        typeof value.created_at === "string" && value.synthetic === true)
    ).slice(0, MAX_OUTBOX_ITEMS);
  } catch {
    return [];
  }
}

export function saveSyntheticCapture(
  storage: StorageLike,
  text: string,
  now: string,
  id: string,
): SyntheticCapture[] | null {
  const trimmed = text.trim().slice(0, 500);
  if (!trimmed) return null;
  const next: SyntheticCapture[] = [
    { id, text: trimmed, created_at: now, synthetic: true as const },
    ...loadSyntheticOutbox(storage),
  ].slice(0, MAX_OUTBOX_ITEMS);
  storage.setItem(OUTBOX_KEY, JSON.stringify(next));
  return next;
}
