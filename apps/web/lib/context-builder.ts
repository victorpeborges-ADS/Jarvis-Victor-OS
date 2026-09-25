import type { ContextBundle, SourceRef } from "@/lib/mission-contracts";

export interface ContextCandidate extends SourceRef {
  content: string;
  project_id?: string | null;
}

export interface ContextBuildOptions {
  task_id: string;
  mission_id: string;
  allowed_source_ids: ReadonlySet<string>;
  allowed_domains: ReadonlySet<string>;
  domain_id: string | null;
  project_id?: string | null;
  now: string;
  max_bytes: number;
}

export interface ContextBuildResult { bundle: ContextBundle; text: string; }

function bytes(value: string): number { return new TextEncoder().encode(value).length; }

export function buildTaskContext(sources: ContextCandidate[], options: ContextBuildOptions): ContextBuildResult {
  const included: SourceRef[] = [];
  const omitted: ContextBundle["omitted"] = [];
  const excerpts: string[] = [];
  let usedBytes = 0;
  const nowMs = Date.parse(options.now);
  const freshnessMs = 24 * 60 * 60 * 1000;

  for (const source of sources) {
    // The grant check deliberately runs before domain, recency, or content checks.
    if (!options.allowed_source_ids.has(source.source_id)) {
      omitted.push({ source_id: source.source_id, reason: "grant_denied" });
      continue;
    }
    if (!source.domain_id || source.domain_id !== options.domain_id || !options.allowed_domains.has(source.domain_id)) {
      omitted.push({ source_id: source.source_id, reason: "wrong_domain" });
      continue;
    }
    if (options.project_id && source.project_id !== options.project_id) {
      omitted.push({ source_id: source.source_id, reason: "wrong_project" });
      continue;
    }
    if (source.valid_until && Date.parse(source.valid_until) <= nowMs) {
      omitted.push({ source_id: source.source_id, reason: "expired" });
      continue;
    }
    if (!source.last_verified_at || nowMs - Date.parse(source.last_verified_at) > freshnessMs) {
      omitted.push({ source_id: source.source_id, reason: "stale" });
      continue;
    }
    const excerpt = `${source.source_id}: ${JSON.stringify(source.content)}`;
    const excerptBytes = bytes(excerpt);
    if (usedBytes + excerptBytes > options.max_bytes) {
      omitted.push({ source_id: source.source_id, reason: "over_budget" });
      continue;
    }
    usedBytes += excerptBytes;
    included.push({ source_id: source.source_id, uri: source.uri ?? null, observed_at: source.observed_at, last_verified_at: source.last_verified_at, valid_until: source.valid_until ?? null, domain_id: source.domain_id });
    // JSON quoting keeps source text visibly in a data position, including any instruction-like text.
    excerpts.push(`[DADO DE FONTE SINTÉTICA ${source.source_id}] ${JSON.stringify(source.content)}`);
  }

  return {
    bundle: {
      id: `context_${options.mission_id}_${options.task_id}`,
      task_id: options.task_id,
      included,
      omitted,
      size_bytes: usedBytes,
      budget_bytes: options.max_bytes,
      created_at: options.now
    },
    text: excerpts.join("\n")
  };
}
