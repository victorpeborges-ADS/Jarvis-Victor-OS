import type { HandoffBundle, ProviderCapabilities, SourceRef } from "@/lib/mission-contracts";

export interface IntelligenceRequest {
  capability: ProviderCapabilities["capabilities"][number];
  classification: "synthetic_only" | "local_private" | "sensitive" | "restricted";
  objective: string;
  minimal_context: string;
  source_refs: SourceRef[];
  artifact_ids: string[];
  budget_cap: 0;
}

export interface ProviderResponse { provider_id: string; text: string; }

export interface IntelligenceProvider extends ProviderCapabilities {
  run(request: IntelligenceRequest): ProviderResponse;
}

export class FakeProvider implements IntelligenceProvider {
  readonly provider_id = "fake-provider";
  readonly capabilities: ProviderCapabilities["capabilities"] = ["summarize", "classify", "draft"];
  readonly enabled = true;
  readonly privacy = "synthetic_only" as const;
  readonly cost_cap = 0 as const;

  run(request: IntelligenceRequest): ProviderResponse {
    const compact = request.minimal_context.replace(/\s+/g, " ").trim().slice(0, 240);
    return { provider_id: this.provider_id, text: `[FAKE · ${request.capability}] ${request.objective.trim()} — ${compact || "sem contexto"}` };
  }
}

export interface RouterResult {
  status: "completed" | "no_llm";
  provider_id: string | null;
  text: string;
  cost_cap: 0;
  reason?: string;
}

export class IntelligenceRouter {
  private readonly providers: IntelligenceProvider[];
  readonly cost_cap = 0 as const;

  constructor(providers: IntelligenceProvider[] = [new FakeProvider()]) {
    this.providers = providers;
  }

  run(request: IntelligenceRequest): RouterResult {
    if (request.budget_cap !== 0) return { status: "no_llm", provider_id: null, text: request.minimal_context, cost_cap: 0, reason: "orçamento fora da política fixa zero" };
    if (request.classification !== "synthetic_only") return { status: "no_llm", provider_id: null, text: request.minimal_context, cost_cap: 0, reason: "classificação não permitida para o FakeProvider" };
    const provider = this.providers.find((candidate) => candidate.enabled && candidate.privacy === "synthetic_only" && candidate.cost_cap === 0 && candidate.capabilities.includes(request.capability));
    if (!provider) return { status: "no_llm", provider_id: null, text: request.minimal_context, cost_cap: 0, reason: "sem provider determinístico elegível; contexto fica disponível sem LLM" };
    return { status: "completed", provider_id: provider.provider_id, text: provider.run(request).text, cost_cap: 0 };
  }
}

/** Produces a reviewable handoff envelope. This function never opens a chat or sends data. */
export function createManualHandoff(request: IntelligenceRequest, id: string, now: string, approvals: string[]): HandoffBundle {
  return {
    version: 1,
    id: `handoff_${id}`,
    destination: "chatgpt_work",
    objective: request.objective.slice(0, 1000),
    minimal_context: request.minimal_context.slice(0, 10000),
    source_refs: request.source_refs,
    restrictions: ["transmissão manual; revisar o contexto antes de copiar", "não executar ações externas sem aprovação explícita"],
    approvals,
    artifacts: request.artifact_ids,
    transmission: "manual_only",
    created_at: now
  };
}
