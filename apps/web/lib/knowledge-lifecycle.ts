import type { KnowledgeItem } from "@/lib/mission-contracts";

export type KnowledgeTransition = "stage" | "review" | "approve" | "reject" | "archive" | "delete";

const transitions: Record<KnowledgeTransition, KnowledgeItem["state"][]> = {
  stage: ["captured"],
  review: ["staged"],
  approve: ["reviewed"],
  reject: ["reviewed"],
  archive: ["approved", "rejected", "stale", "expired"],
  delete: ["captured", "staged", "reviewed", "approved", "rejected", "stale", "expired", "archived"]
};

export function transitionKnowledge(item: KnowledgeItem, action: KnowledgeTransition, now: string, reviewer?: string): KnowledgeItem {
  if (!transitions[action].includes(item.state)) return item;
  if (action === "approve" && (item.kind === "ai_derived" && item.source_refs.length === 0)) return item;
  const next = action === "stage" ? "staged" : action === "review" ? "reviewed" : action === "approve" ? "approved" : action === "reject" ? "rejected" : action === "archive" ? "archived" : "deleted";
  return { ...item, state: next, reviewer: action === "approve" || action === "reject" ? reviewer ?? item.reviewer : item.reviewer, updated_at: now };
}

export function markKnowledgeExpired(item: KnowledgeItem, now: string): KnowledgeItem {
  if (!item.valid_until || Date.parse(item.valid_until) > Date.parse(now) || ["deleted", "archived", "expired"].includes(item.state)) return item;
  return { ...item, state: "expired", updated_at: now };
}

export function markDependentsAfterSourceChange(items: KnowledgeItem[], sourceId: string, now: string): Array<{ item: KnowledgeItem; reviewRequired: boolean }> {
  return items.map((item) => {
    const referencesSource = item.source_refs.some((source) => source.source_id === sourceId);
    if (!referencesSource || ["deleted", "archived"].includes(item.state)) return { item, reviewRequired: false };
    if (item.kind === "approved_decision") return { item, reviewRequired: true };
    if (["ai_derived", "imported", "reference"].includes(item.kind) && item.state !== "stale") {
      return { item: { ...item, state: "stale", updated_at: now }, reviewRequired: true };
    }
    return { item, reviewRequired: false };
  });
}

/** Original/imported source text is immutable here; corrections become a new item. */
export function replaceKnowledgeText(item: KnowledgeItem, nextText: string, now: string): { item: KnowledgeItem; replaced: boolean } {
  if (item.kind !== "human_note" || item.state === "deleted") return { item, replaced: false };
  return { item: { ...item, content: nextText, updated_at: now }, replaced: true };
}
