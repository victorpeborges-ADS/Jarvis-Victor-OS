import type { Artifact, KnowledgeItem, Mission, SkillManifest, SourceRef } from "@/lib/mission-contracts";
import { buildTaskContext, type ContextBuildOptions, type ContextBuildResult, type ContextCandidate } from "@/lib/context-builder";

export const SYNTHETIC_SKILLS: SkillManifest[] = [
  { id: "capture-and-classify", version: "1.0.0", purpose: "Capturar conteúdo sintético e classificar apenas por regra determinística.", inputs: ["text", "domain_id"], outputs: ["knowledge_item"], tool_allowlist: ["read_synthetic", "write_local_draft"], domains: [], side_effects: ["local_draft"], approval: "none", privacy: "synthetic_only", cost_cap: 0, timeout_seconds: 5, retries: 0 },
  { id: "build-context", version: "1.0.0", purpose: "Minimizar fontes no cliente por escopo, validade e orçamento; não concede acesso.", inputs: ["sources", "client_minimization_policy", "budget"], outputs: ["context_bundle"], tool_allowlist: ["build_context"], domains: [], side_effects: ["none"], approval: "none", privacy: "synthetic_only", cost_cap: 0, timeout_seconds: 5, retries: 0 },
  { id: "draft-evidenced-report", version: "1.0.0", purpose: "Criar um rascunho determinístico com referências de proveniência.", inputs: ["mission", "source_refs"], outputs: ["artifact"], tool_allowlist: ["read_synthetic", "write_local_draft"], domains: [], side_effects: ["local_draft"], approval: "none", privacy: "synthetic_only", cost_cap: 0, timeout_seconds: 5, retries: 0 },
  { id: "compare-sources", version: "1.0.0", purpose: "Comparar textos sintéticos já minimizados no cliente; não concede acesso.", inputs: ["client_filtered_sources"], outputs: ["comparison_artifact"], tool_allowlist: ["compare_sources", "write_local_draft"], domains: [], side_effects: ["local_draft"], approval: "none", privacy: "synthetic_only", cost_cap: 0, timeout_seconds: 5, retries: 0 }
];

export function captureAndClassify(text: string, domainId: string | null, now: string, id: string): KnowledgeItem {
  const normalized = text.trim().slice(0, 50000);
  return {
    id: `knowledge_${id}`, kind: "human_note", state: "captured", content: normalized,
    domain_id: domainId, source_refs: [], skill_version: "1.0.0", model_version: null,
    author: "usuário local", reviewer: null, valid_until: null, created_at: now, updated_at: now
  };
}

export function buildContextSkill(sources: ContextCandidate[], options: ContextBuildOptions): ContextBuildResult {
  return buildTaskContext(sources, options);
}

export function draftEvidencedReport(mission: Mission, sources: SourceRef[], now: string, id: string): Artifact {
  return {
    id: `artifact_${id}`, kind: "report", title: `Rascunho: ${mission.title}`,
    content: `Resumo sintético da missão “${mission.title}”. Etapas concluídas: ${mission.tasks.filter((task) => task.status === "done").length} de ${mission.tasks.length}. Rascunho local aguardando revisão humana; nenhuma informação foi enviada.`,
    skill_version: "1.0.0", review_state: "awaiting_approval", reviewed_at: null, source_refs: sources, created_at: now
  };
}

/** Deterministic comparison helper. Callers must supply an already minimized set; this is not authorization. */
export function compareClientFilteredSources(sources: ContextCandidate[], now: string, id: string): Artifact {
  const same = sources.length < 2 || sources.every((source) => source.content === sources[0].content);
  const sourceRefs = sources.map(({ source_id, uri, observed_at, last_verified_at, valid_until, domain_id }) => ({ source_id, uri: uri ?? null, observed_at, last_verified_at: last_verified_at ?? null, valid_until: valid_until ?? null, domain_id: domain_id ?? null }));
  return {
    id: `artifact_${id}`, kind: "evidence", title: "Comparação sintética de fontes",
    content: sources.length < 2 ? "São necessárias duas fontes autorizadas para comparar." : same ? "Os textos sintéticos são idênticos." : "Os textos sintéticos diferem por comparação exata.",
    skill_version: "1.0.0", source_refs: sourceRefs, created_at: now
  };
}
