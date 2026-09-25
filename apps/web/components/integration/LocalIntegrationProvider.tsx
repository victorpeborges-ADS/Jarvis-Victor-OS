"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode
} from "react";
import { usePathname } from "next/navigation";
import {
  LocalApiError, localApiRequest, type CalendarSyncReport, type CalendarSyncState,
  type LocalGrant, type LocalSession, type RealEvent, type SimulatedCalendar
} from "@/lib/local-api";

export const SYNTHETIC_DOMAINS = [
  { id: "dom_synthetic_a", label: "Escopo sintético A" },
  { id: "dom_synthetic_b", label: "Escopo sintético B" },
  { id: "dom_synthetic_c", label: "Escopo sintético C" },
  { id: "dom_synthetic_d", label: "Escopo sintético D" },
  { id: "dom_synthetic_e", label: "Escopo sintético E" },
  { id: "dom_synthetic_f", label: "Escopo sintético F" },
  { id: "dom_synthetic_g", label: "Escopo sintético G" },
  { id: "dom_synthetic_h", label: "Escopo sintético H" }
] as const;
export type SyntheticDomainId = (typeof SYNTHETIC_DOMAINS)[number]["id"];
export type AuthStatus = "checking" | "anonymous" | "authenticated";

type IntegrationContextValue = {
  authStatus: AuthStatus;
  expiresAt: string | null;
  csrfAvailable: boolean;
  notice: string | null;
  calendars: SimulatedCalendar[];
  grants: LocalGrant[];
  states: CalendarSyncState[];
  events: RealEvent[];
  selectedDomain: SyntheticDomainId;
  resourcesLoading: boolean;
  eventsLoading: boolean;
  lastReport: CalendarSyncReport | null;
  login(passphrase: string): Promise<boolean>;
  logout(): Promise<void>;
  loadResources(): Promise<void>;
  createGrant(domainId: SyntheticDomainId): Promise<void>;
  createInventoryGrant(domainId: SyntheticDomainId): Promise<void>;
  revokeGrant(grant: LocalGrant): Promise<void>;
  classifyCalendar(calendarId: string, domainId: SyntheticDomainId): Promise<void>;
  syncCalendar(calendarId: string): Promise<void>;
  selectDomain(domainId: SyntheticDomainId): Promise<void>;
  refreshEvents(): Promise<void>;
  clearNotice(): void;
};

const IntegrationContext = createContext<IntegrationContextValue | null>(null);

function isSession(value: unknown): value is LocalSession {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return item.dataset === "real" && typeof item.csrf_token === "string" &&
    item.csrf_token.length >= 32 && typeof item.expires_at === "string" &&
    Number.isFinite(Date.parse(item.expires_at));
}

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function domainHasGrant(grants: LocalGrant[], domainId: string): boolean {
  return grants.some((grant) => grant.connector === "calendar_sim" &&
    grant.permission === "read" && grant.resource_ids.includes("calendar:synthetic-primary") &&
    grant.domain_ids.includes(domainId) &&
    Date.parse(grant.expires_at) > Date.now() && !grant.revoked);
}

export function LocalIntegrationProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [authStatus, setAuthStatus] = useState<AuthStatus>("checking");
  const [csrf, setCsrf] = useState<string | null>(null);
  const csrfRef = useRef<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [calendars, setCalendars] = useState<SimulatedCalendar[]>([]);
  const [grants, setGrants] = useState<LocalGrant[]>([]);
  const [states, setStates] = useState<CalendarSyncState[]>([]);
  const [events, setEvents] = useState<RealEvent[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<SyntheticDomainId>("dom_synthetic_a");
  const [resourcesLoading, setResourcesLoading] = useState(false);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [lastReport, setLastReport] = useState<CalendarSyncReport | null>(null);
  const generation = useRef(0);
  const controllers = useRef(new Set<AbortController>());

  const cancelPending = useCallback((except?: AbortController) => {
    generation.current += 1;
    for (const controller of controllers.current) {
      if (controller !== except) controller.abort();
    }
    if (except) controllers.current = new Set([except]);
    else controllers.current.clear();
  }, []);

  const clearProtectedData = useCallback(() => {
    cancelPending();
    setCalendars([]);
    setGrants([]);
    setStates([]);
    setEvents([]);
    setLastReport(null);
    setResourcesLoading(false);
    setEventsLoading(false);
  }, [cancelPending]);

  const invalidateSession = useCallback((message: string, except?: AbortController) => {
    cancelPending(except);
    csrfRef.current = null;
    setCsrf(null);
    setExpiresAt(null);
    setAuthStatus("anonymous");
    setCalendars([]);
    setGrants([]);
    setStates([]);
    setEvents([]);
    setLastReport(null);
    setResourcesLoading(false);
    setEventsLoading(false);
    setNotice(message);
  }, [cancelPending]);

  const requestJson = useCallback(async <T,>(
    path: string,
    options: { method?: string; body?: unknown; csrfRequired?: boolean; allowMissingSession?: boolean; keepSessionOnForbidden?: boolean } = {}
  ): Promise<T | undefined> => {
    const controller = new AbortController();
    const requestGeneration = generation.current;
    controllers.current.add(controller);
    const headers = new Headers();
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    if (options.csrfRequired) {
      if (!csrfRef.current) throw new LocalApiError(401, "Sessão não está disponível.");
      headers.set("X-CSRF-Token", csrfRef.current);
    }
    try {
      const { data } = await localApiRequest<T>(path, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal
      });
      if (requestGeneration !== generation.current) return undefined;
      return data;
    } catch (error) {
      if (controller.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) return undefined;
      if (error instanceof LocalApiError) {
        if (options.allowMissingSession && error.status === 401) return undefined;
        if (options.keepSessionOnForbidden && error.status === 403) {
          setNotice(error.message);
          return undefined;
        }
        if (error.status === 401 || error.status === 403) invalidateSession(error.message, controller);
        else setNotice(error.message);
      } else {
        setNotice("Não foi possível alcançar a API local. Verifique se o servidor oficial está ativo em loopback.");
        setEvents([]);
      }
      throw error;
    } finally {
      controllers.current.delete(controller);
    }
  }, [invalidateSession]);

  const acceptSession = useCallback((value: unknown): boolean => {
    if (!isSession(value)) {
      invalidateSession("A API local devolveu uma sessão inválida. Entre novamente.");
      return false;
    }
    csrfRef.current = value.csrf_token;
    setCsrf(value.csrf_token);
    setExpiresAt(value.expires_at);
    setAuthStatus("authenticated");
    setNotice(null);
    return true;
  }, [invalidateSession]);

  useEffect(() => {
    if (pathname !== "/integrado") {
      csrfRef.current = null;
      setCsrf(null);
      setExpiresAt(null);
      setAuthStatus("anonymous");
      return;
    }
    let mounted = true;
    void requestJson<LocalSession>("/real/session", { allowMissingSession: true })
      .then((value) => {
        if (!mounted) return;
        if (value) acceptSession(value);
        else {
          csrfRef.current = null;
          setCsrf(null);
          setExpiresAt(null);
          setAuthStatus("anonymous");
        }
      })
      .catch(() => {
        if (mounted) setAuthStatus("anonymous");
      });
    return () => { mounted = false; };
  }, [acceptSession, pathname, requestJson]);

  useEffect(() => {
    if (authStatus !== "authenticated" || !expiresAt) return;
    const delay = Math.max(0, Date.parse(expiresAt) - Date.now());
    const timer = window.setTimeout(
      () => invalidateSession("A sessão local expirou. Entre novamente."),
      Math.min(delay, 2_147_000_000)
    );
    return () => window.clearTimeout(timer);
  }, [authStatus, expiresAt, invalidateSession]);

  useEffect(() => {
    if (pathname !== "/integrado") clearProtectedData();
  }, [pathname, clearProtectedData]);

  const loadResourcesFromServer = useCallback(async () => {
    const activeGrants = await requestJson<LocalGrant[]>("/real/grants");
    if (!activeGrants) return;
    const safeGrantsValue = safeArray<LocalGrant>(activeGrants);
    const hasCalendarRead = safeGrantsValue.some((grant) => domainHasGrant([grant], grant.domain_ids[0] ?? ""));
    if (!hasCalendarRead) {
      setGrants(safeGrantsValue);
      setStates([]);
      setCalendars([]);
      setNotice("Sessão autenticada sem concessão de leitura do Calendar. A API recusa o estado com 403; isto não é um catálogo vazio nem o modo DEMO.");
      return;
    }
    const calendarStates = await requestJson<{ provider_mode: "simulated"; states: CalendarSyncState[] }>(
      "/real/calendar-sim/state",
      { keepSessionOnForbidden: true }
    );
    if (!calendarStates) return;
    if (calendarStates.provider_mode !== "simulated") {
      invalidateSession("A resposta da API não corresponde ao modo simulado esperado.");
      return;
    }
    const safeStatesValue = safeArray<CalendarSyncState>(calendarStates.states);
    const catalog = await requestJson<{ provider_mode: "simulated"; calendars: SimulatedCalendar[] }>("/real/calendar-sim/calendars");
    if (!catalog) return;
    if (catalog.provider_mode !== "simulated") {
      invalidateSession("A resposta da API não corresponde ao modo simulado esperado.");
      return;
    }
    // Do not publish states before the catalog request finishes: the page's
    // state effect starts an event refresh that cancels pending requests.
    setNotice(null);
    setGrants(safeGrantsValue);
    setStates(safeStatesValue);
    setCalendars(safeArray<SimulatedCalendar>(catalog.calendars));
  }, [invalidateSession, requestJson]);

  const loadResources = useCallback(async () => {
    if (authStatus !== "authenticated") return;
    setResourcesLoading(true);
    setNotice(null);
    try {
      await loadResourcesFromServer();
    } catch {
      // requestJson stores a safe, user-facing message. Raw response bodies are
      // intentionally never rendered.
    } finally {
      setResourcesLoading(false);
    }
  }, [authStatus, loadResourcesFromServer]);

  const refreshEvents = useCallback(async (domainId: SyntheticDomainId = selectedDomain) => {
    cancelPending();
    setEvents([]);
    setNotice(null);
    if (authStatus !== "authenticated" || !domainHasGrant(grants, domainId)) {
      setEventsLoading(false);
      return;
    }
    setEventsLoading(true);
    try {
      const result = await requestJson<RealEvent[]>(`/real/events?domain_id=${encodeURIComponent(domainId)}`);
      if (result) setEvents(safeArray<RealEvent>(result));
    } catch {
      // Protected results remain empty on authorization or transport errors.
    } finally {
      setEventsLoading(false);
    }
  }, [authStatus, cancelPending, grants, requestJson, selectedDomain]);

  const login = useCallback(async (passphrase: string): Promise<boolean> => {
    clearProtectedData();
    setAuthStatus("anonymous");
    setNotice(null);
    try {
      const value = await requestJson<LocalSession>("/real/session", {
        method: "POST",
        body: { passphrase }
      });
      return value ? acceptSession(value) : false;
    } catch {
      return false;
    }
  }, [acceptSession, clearProtectedData, requestJson]);

  const logout = useCallback(async () => {
    if (authStatus !== "authenticated") return;
    try {
      await requestJson<void>("/real/session", { method: "DELETE", csrfRequired: true });
      invalidateSession("Sessão encerrada. Nenhum dado integrado permanece nesta tela.");
    } catch {
      // A request handler already invalidates protected state on 401/403.
    }
  }, [authStatus, invalidateSession, requestJson]);

  const loadResourcesAfterMutation = useCallback(async () => {
    try { await loadResourcesFromServer(); }
    catch { /* requestJson stores a safe message and clears protected data on failure. */ }
  }, [loadResourcesFromServer]);

  const postGrant = useCallback(async (domainId: SyntheticDomainId, resourceId: string) => {
    const result = await requestJson<LocalGrant>("/real/grants", {
      method: "POST",
      csrfRequired: true,
      body: {
        connector: "calendar_sim",
        permission: "read",
        resource_ids: [resourceId],
        domain_ids: [domainId],
        expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
      }
    });
    if (result) {
      setGrants((current) => [...current.filter((grant) => grant.id !== result.id), result]);
      await loadResourcesAfterMutation();
    }
  }, [loadResourcesAfterMutation, requestJson]);

  const createGrant = useCallback(async (domainId: SyntheticDomainId) => {
    await postGrant(domainId, "calendar:synthetic-primary");
  }, [postGrant]);

  const createInventoryGrant = useCallback(async (domainId: SyntheticDomainId) => {
    await postGrant(domainId, "calendar:synthetic-inventory");
  }, [postGrant]);

  const revokeGrant = useCallback(async (grant: LocalGrant) => {
    cancelPending();
    setEvents([]);
    setStates((current) => current.filter((state) => state.domain_id !== grant.domain_ids[0]));
    const result = await requestJson<{ id: string; revoked: boolean }>(
      `/real/grants/${encodeURIComponent(grant.id)}/revoke`,
      { method: "POST", csrfRequired: true }
    );
    if (result?.revoked) {
      setGrants((current) => current.filter((item) => item.id !== grant.id));
      await loadResourcesAfterMutation();
    }
  }, [cancelPending, loadResourcesAfterMutation, requestJson]);

  const classifyCalendar = useCallback(async (calendarId: string, domainId: SyntheticDomainId) => {
    const result = await requestJson<{ calendar_id: string; domain_id: string; provider_mode: "simulated" }>(
      `/real/calendar-sim/calendars/${encodeURIComponent(calendarId)}/classification`,
      { method: "PUT", csrfRequired: true, body: { domain_id: domainId } }
    );
    if (result?.provider_mode === "simulated") await loadResourcesAfterMutation();
  }, [loadResourcesAfterMutation, requestJson]);

  const syncCalendar = useCallback(async (calendarId: string) => {
    const result = await requestJson<CalendarSyncReport>("/real/calendar-sim/sync", {
      method: "POST", csrfRequired: true, body: { calendar_id: calendarId }
    });
    if (!result || result.dataset !== "real" || result.provider_mode !== "simulated") return;
    setLastReport(result);
    await loadResourcesAfterMutation();
  }, [loadResourcesAfterMutation, requestJson]);

  const selectDomain = useCallback(async (domainId: SyntheticDomainId) => {
    setSelectedDomain(domainId);
    await refreshEvents(domainId);
  }, [refreshEvents]);

  const value = useMemo<IntegrationContextValue>(() => ({
    authStatus, expiresAt, csrfAvailable: Boolean(csrf), notice, calendars, grants, states, events,
    selectedDomain, resourcesLoading, eventsLoading, lastReport, login, logout, loadResources,
    createGrant, createInventoryGrant, revokeGrant, classifyCalendar, syncCalendar, selectDomain, refreshEvents,
    clearNotice: () => setNotice(null)
  }), [
    authStatus, expiresAt, csrf, notice, calendars, grants, states, events, selectedDomain,
    resourcesLoading, eventsLoading, lastReport, login, logout, loadResources, createGrant, createInventoryGrant,
    revokeGrant, classifyCalendar, syncCalendar, selectDomain, refreshEvents
  ]);

  return <IntegrationContext.Provider value={value}>{children}</IntegrationContext.Provider>;
}

export function useLocalIntegration(): IntegrationContextValue {
  const value = useContext(IntegrationContext);
  if (!value) throw new Error("LocalIntegrationProvider ausente");
  return value;
}
