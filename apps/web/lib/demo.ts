import demo from "../../../fixtures/demo.json";

// Re-export tipos mínimos
export type Source = (typeof demo.sources)[number];
export type EventItem = (typeof demo.events)[number];
export type Proposal = (typeof demo.proposals)[number];
export type InboxItem = (typeof demo.inbox)[number];
export type Approval = (typeof demo.approvals)[number];
export type SyncStatus = Source["sync_status"];

export const fixtures = demo;

/** Horário de referência da demonstração para manter os dados coerentes. */
export const DEMO_NOW = fixtures.meta.generated_at;

export function getEvent(id: string) {
  return demo.events.find((e) => e.id === id);
}
export function getEntity(id: string) {
  return demo.entities.find((e) => e.id === id);
}
export function getSource(id: string) {
  return demo.sources.find((s) => s.id === id);
}

export function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Sao_Paulo"
  });
}

/** Horário editorial PT-BR: 09h30 */
export function formatTimeH(iso: string) {
  return formatTime(iso).replace(":", "h");
}

export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    timeZone: "America/Sao_Paulo"
  });
}

export function greetingFromHour(iso: string = DEMO_NOW): string {
  const hour = Number(
    new Date(iso).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      hour12: false,
      timeZone: "America/Sao_Paulo"
    }).slice(0, 2)
  );
  if (hour < 12) return "Bom dia";
  if (hour < 18) return "Boa tarde";
  return "Boa noite";
}

export function minutesUntil(targetIso: string, nowIso: string = DEMO_NOW): number {
  return Math.round((new Date(targetIso).getTime() - new Date(nowIso).getTime()) / 60000);
}

export function formatMinutesUntil(targetIso: string, nowIso: string = DEMO_NOW): string {
  const mins = minutesUntil(targetIso, nowIso);
  if (mins <= 0) return "agora";
  if (mins < 60) return `em ${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `em ${h} h` : `em ${h} h ${m} min`;
}

export function commitmentsToday() {
  return fixtures.events
    .filter((e) => e.event_type === "commitment" && e.show_in_agora !== false)
    .slice()
    .sort((a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime());
}

export function messagesToday() {
  return fixtures.events
    .filter((e) => e.event_type === "communication" && e.show_in_agora !== false)
    .slice()
    .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
}

/** Os estados de exemplo não se confundem com uma conexão ativa. */
export function syncStatusLabel(status: SyncStatus): string {
  if (status === "connected") return "exemplo · atualizado";
  if (status === "stale") return "exemplo · desatualizado";
  if (status === "error") return "exemplo · indisponível";
  return `exemplo · ${status}`;
}

export function sensitivityLabel(s: string): string {
  const map: Record<string, string> = {
    internal: "interno",
    personal: "pessoal",
    public: "público"
  };
  return map[s] ?? s;
}

export function inboxStatusLabel(s: string): string {
  const map: Record<string, string> = {
    classified: "classificado",
    pending: "pendente",
    archived: "arquivado"
  };
  return map[s] ?? s;
}

export function providerLabel(provider: string): string {
  const map: Record<string, string> = {
    google_calendar: "Google Calendar",
    gmail: "Gmail",
    google_drive: "Google Drive"
  };
  return map[provider] ?? provider;
}
