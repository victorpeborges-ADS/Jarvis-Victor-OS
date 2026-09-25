import type { ContextBundle, SourceRef } from "@/lib/mission-contracts";
import { isValidTimestamp } from "@/lib/mission-validation";

export interface ContextCandidate extends SourceRef {
  content: string;
  project_id?: string | null;
}

export interface ContextBuildOptions {
  task_id: string;
  mission_id: string;
  client_visible_source_ids: ReadonlySet<string>;
  client_visible_domains: ReadonlySet<string>;
  domain_id: string | null;
  project_id?: string | null;
  now: string;
  max_bytes: number;
}

export interface ContextBuildResult { bundle: ContextBundle; text: string; }

function bytes(value: string): number { return new TextEncoder().encode(value).length; }

export function buildTaskContext(sources: ContextCandidate[], options: ContextBuildOptions): ContextBuildResult {
  // This is client-side data minimization only. These sets are caller inputs,
  // not credentials or an authorization decision; the API must enforce grants
  // independently for every server query.
  const included: SourceRef[] = [];
  const omitted: ContextBundle["omitted"] = [];
  const excerpts: string[] = [];
  let usedBytes = 0;
  if (!isValidTimestamp(options.now) || !Number.isSafeInteger(options.max_bytes) || options.max_bytes < 0) {
    throw new RangeError("instante de contexto ou orçamento inválido");
  }
  const requestedNow = Date.parse(options.now);
  // A caller cannot advance the context clock to make a future verification
  // appear current. The API remains authoritative for server-side access.
  const nowMs = Math.min(requestedNow, Date.now());
  const effectiveNow = new Date(nowMs).toISOString();
  const freshnessMs = 24 * 60 * 60 * 1000;

  for (const source of sources) {
    // Client-side minimization runs before domain, recency, or content checks.
    if (!options.client_visible_source_ids.has(source.source_id)) {
      omitted.push({ source_id: source.source_id, reason: "not_client_visible" });
      continue;
    }
    if (!source.domain_id || source.domain_id !== options.domain_id || !options.client_visible_domains.has(source.domain_id)) {
      omitted.push({ source_id: source.source_id, reason: "wrong_domain" });
      continue;
    }
    if (options.project_id && source.project_id !== options.project_id) {
      omitted.push({ source_id: source.source_id, reason: "wrong_project" });
      continue;
    }
    if (!isValidTimestamp(source.observed_at)) {
      omitted.push({ source_id: source.source_id, reason: "invalid_timestamp" });
      continue;
    }
    if (Date.parse(source.observed_at) > nowMs) {
      omitted.push({ source_id: source.source_id, reason: "future_timestamp" });
      continue;
    }
    if (source.valid_until != null && !isValidTimestamp(source.valid_until)) {
      omitted.push({ source_id: source.source_id, reason: "invalid_timestamp" });
      continue;
    }
    if (source.valid_until && Date.parse(source.valid_until) <= nowMs) {
      omitted.push({ source_id: source.source_id, reason: "expired" });
      continue;
    }
    if (source.last_verified_at != null && !isValidTimestamp(source.last_verified_at)) {
      omitted.push({ source_id: source.source_id, reason: "invalid_timestamp" });
      continue;
    }
    if (source.last_verified_at && Date.parse(source.last_verified_at) > nowMs) {
      omitted.push({ source_id: source.source_id, reason: "future_verification" });
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
      created_at: effectiveNow
    },
    text: excerpts.join("\n")
  };
}
