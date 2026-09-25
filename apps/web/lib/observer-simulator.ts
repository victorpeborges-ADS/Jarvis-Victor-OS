import type { NotificationPolicy } from "@/lib/mission-contracts";

export interface SyntheticChange {
  id: string;
  source_id: string;
  domain_id: string | null;
  severity: "normal" | "critical";
  summary: string;
  created_at: string;
}

export interface ObserverResult {
  source: "synthetic_fixture";
  mode: "read_only";
  included: SyntheticChange[];
  omitted: Array<{ id: string; reason: "grant_denied" | "wrong_domain" | "disabled" }>;
  notification: "in_app" | "suppressed";
  side_effects: [];
}

export interface WorkflowAdapter {
  readonly mode: "simulation_only";
  run(changes: SyntheticChange[], policy: NotificationPolicy, grants: ReadonlySet<string>, domains: ReadonlySet<string>, now: string): ObserverResult;
}

function isQuiet(policy: NotificationPolicy, now: string): boolean {
  if (!policy.quiet_hours) return false;
  try {
    const local = new Intl.DateTimeFormat("en-GB", { timeZone: policy.quiet_hours.timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(now));
    const [hour, minute] = local.split(":").map(Number);
    const current = hour * 60 + minute;
    const [startHour, startMinute] = policy.quiet_hours.start.split(":").map(Number);
    const [endHour, endMinute] = policy.quiet_hours.end.split(":").map(Number);
    const start = startHour * 60 + startMinute;
    const end = endHour * 60 + endMinute;
    return start <= end ? current >= start && current < end : current >= start || current < end;
  } catch {
    return true;
  }
}

export class FakeWorkflowAdapter implements WorkflowAdapter {
  readonly mode = "simulation_only" as const;

  run(changes: SyntheticChange[], policy: NotificationPolicy, grants: ReadonlySet<string>, domains: ReadonlySet<string>, now: string): ObserverResult {
    const included: SyntheticChange[] = [];
    const omitted: ObserverResult["omitted"] = [];
    for (const change of changes) {
      if (!grants.has(change.source_id)) {
        omitted.push({ id: change.id, reason: "grant_denied" });
        continue;
      }
      if (!change.domain_id || !domains.has(change.domain_id)) {
        omitted.push({ id: change.id, reason: "wrong_domain" });
        continue;
      }
      included.push(change);
    }
    const criticalOnly = policy.interruptions === "critical_only";
    const hasEligible = policy.enabled && included.some((change) => !criticalOnly || change.severity === "critical");
    const quiet = isQuiet(policy, now);
    const notification = hasEligible && !quiet && policy.channels.includes("in_app") && policy.interruptions !== "never" ? "in_app" : "suppressed";
    if (!policy.enabled) {
      for (const change of included.splice(0)) omitted.push({ id: change.id, reason: "disabled" });
    }
    return { source: "synthetic_fixture", mode: "read_only", included, omitted, notification, side_effects: [] };
  }
}
