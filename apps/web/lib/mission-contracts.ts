/** Versioned shared contracts. JSON Schema is the serialized wire contract. */
export type MissionStatus = "draft" | "planned" | "awaiting_approval" | "running" | "blocked" | "done" | "cancelled" | "failed";
export type Timestamp = string;

export interface SourceRef {
  source_id: string;
  uri?: string | null;
  observed_at: Timestamp;
  last_verified_at?: Timestamp | null;
  valid_until?: Timestamp | null;
  domain_id?: string | null;
}
export interface MissionTask {
  id: string; title: string; status: MissionStatus; depends_on: string[];
  attempt: number; idempotency_key: string; updated_at: Timestamp; failure_reason?: string | null;
}
export interface MissionCheckpoint { id: string; task_id: string | null; state: "created" | "started" | "completed" | "failed" | "cancelled"; note?: string; created_at: Timestamp; }
export interface MissionEvent { id: string; type: "mission_created" | "task_started" | "task_completed" | "task_failed" | "task_retried" | "mission_cancelled" | "artifact_created"; message: string; task_id?: string | null; created_at: Timestamp; idempotency_key: string; }
export interface Artifact { id: string; kind: "draft" | "report" | "context_bundle" | "evidence"; title: string; content: string; skill_version?: string | null; review_state?: "not_required" | "awaiting_approval" | "approved_locally" | "rejected"; reviewed_at?: Timestamp | null; source_refs: SourceRef[]; created_at: Timestamp; }
export interface ContextBundle { id: string; task_id: string; included: SourceRef[]; omitted: Array<{ source_id: string; reason: "not_client_visible" | "wrong_domain" | "wrong_project" | "stale" | "expired" | "over_budget" | "invalid_timestamp" | "future_timestamp" | "future_verification" }>; size_bytes: number; budget_bytes: number; created_at: Timestamp; }
export interface KnowledgeItem { id: string; kind: "original" | "imported" | "human_note" | "ai_derived" | "approved_decision" | "reference"; state: "captured" | "staged" | "reviewed" | "approved" | "rejected" | "stale" | "expired" | "archived" | "deleted"; content: string; domain_id: string | null; source_refs: SourceRef[]; skill_version: string | null; model_version: string | null; author: string; reviewer: string | null; valid_until: Timestamp | null; created_at: Timestamp; updated_at: Timestamp; }
export interface SkillManifest { id: string; version: string; purpose: string; inputs: string[]; outputs: string[]; tool_allowlist: Array<"read_synthetic" | "write_local_draft" | "build_context" | "compare_sources">; domains: string[]; side_effects: Array<"none" | "local_draft">; approval: "none" | "human_before_run" | "human_before_publish"; privacy: "synthetic_only" | "local_private"; cost_cap: 0; timeout_seconds: number; retries: number; }
export interface ProviderCapabilities { provider_id: string; capabilities: Array<"summarize" | "classify" | "draft">; enabled: boolean; privacy: "synthetic_only" | "local_private" | "external"; cost_cap: 0; }
export interface HandoffBundle { version: 1; id: string; destination: "chatgpt_work"; objective: string; minimal_context: string; source_refs: SourceRef[]; restrictions: string[]; approvals: string[]; artifacts: string[]; transmission: "manual_only"; created_at: Timestamp; }
export interface DeviceGrant { id: string; principal: string; device_id: string; domains: string[]; permissions: Array<"read" | "write_local_draft">; expires_at: Timestamp; revoked: boolean; }
export interface SyncEnvelope { version: 1; id: string; generated_at: Timestamp; cursor: string | null; items: Array<{ id: string; kind: "mission" | "knowledge" | "artifact"; payload?: Record<string, unknown> }>; }
export interface NotificationPolicy { enabled: boolean; channels: Array<"in_app">; interruptions: "never" | "critical_only" | "all"; quiet_hours: null | { start: string; end: string; timezone: string }; }
export interface Mission { schema_version: 1; id: string; title: string; description?: string; status: MissionStatus; domain_id: string | null; tasks: MissionTask[]; checkpoints: MissionCheckpoint[]; events: MissionEvent[]; artifacts: Artifact[]; budget: { cap: 0; spent: 0 }; created_at: Timestamp; updated_at: Timestamp; }
export interface MissionRecord { dataset: "api_synthetic"; owner: string; revision: number; access_class: "synthetic_local"; mission: Mission; }
