export type LocalSession = {
  csrf_token: string;
  dataset: "real";
  expires_at: string;
};

export type LocalGrant = {
  id: string;
  principal: string;
  connector: "calendar_sim";
  permission: "read";
  resource_ids: string[];
  domain_ids: string[];
  expires_at: string;
  revoked: boolean;
};

export type SimulatedCalendar = {
  calendar_id: string;
  name: string;
  time_zone: string;
  provider_mode: "simulated";
};

export type CalendarSyncState = {
  calendar_id: string;
  domain_id: string | null;
  provider_mode: "simulated";
  status: "not_synced" | "simulated" | "stale" | "error";
  last_success_at: string | null;
  last_attempt_at: string | null;
  error_code: "simulated_network" | "invalid_cursor" | "provider_error" | null;
};

export type CalendarSyncReport = {
  dataset: "real";
  provider_mode: "simulated";
  events_written: number;
  cancellations_applied: number;
  quarantined: Array<{ calendar_id: string; reason: "unclassified" | "grant_missing" }>;
  states: CalendarSyncState[];
};

export type RealEvent = {
  id: string;
  source_id: string;
  connector: "calendar_sim";
  resource_id: string;
  domain_id: string;
  title: string;
  event_type: string;
  sensitivity: string;
  occurred_at: string | null;
  end_at: string | null;
  calendar_id: string | null;
  calendar_name: string | null;
  calendar_time_zone: string | null;
  event_time_zone: string | null;
  provider_updated_at: string | null;
  provenance: {
    source_id: string;
    external_ref: string | null;
    observed_at: string;
    last_verified_at: string | null;
    valid_until: string | null;
    confidence: number | null;
    classification_method: "human_review" | "explicit_rule" | "unclassified";
    classified_at: string | null;
  };
  dataset: "real";
};

export class LocalApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "LocalApiError";
  }
}

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (normalized === "localhost" || normalized === "::1" || normalized === "127.0.0.1") return true;
  return false;
}

export function resolveLocalApiBase(configured: string): string {
  try {
    const url = new URL(configured);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !isLoopbackHost(url.hostname) ||
      url.username || url.password || url.search || url.hash ||
      (url.pathname !== "/" && url.pathname !== "")
    ) throw new Error("invalid local API URL");
    return url.origin;
  } catch {
    throw new Error("A API deve usar um endereço loopback explícito.");
  }
}

const pageLoopbackHost = typeof window === "undefined" ? "127.0.0.1" : window.location.hostname;

export const LOCAL_API_BASE = resolveLocalApiBase(
  process.env.NEXT_PUBLIC_JARVIS_API_URL ?? `http://${pageLoopbackHost}:8000`
);

export async function localApiRequest<T>(
  path: string,
  init: RequestInit = {}
): Promise<{ data: T | undefined; response: Response }> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(`${LOCAL_API_BASE}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers
  });
  if (!response.ok) {
    const message = response.status === 401
      ? "Credencial inválida ou sessão local encerrada/expirada. Entre novamente."
      : response.status === 403
        ? "A API local recusou o acesso. Confira a concessão e autentique-se novamente."
        : response.status === 409
          ? "A operação conflita com uma classificação ou concessão existente."
          : response.status === 429
            ? "Muitas tentativas de acesso. Aguarde antes de tentar novamente."
            : `A API local não concluiu a operação (HTTP ${response.status}).`;
    throw new LocalApiError(response.status, message);
  }
  if (response.status === 204) return { data: undefined, response };
  return { data: await response.json() as T, response };
}
