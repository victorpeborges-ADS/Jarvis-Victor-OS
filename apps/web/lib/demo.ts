import demo from "../fixtures/demo.json";

// Re-export tipos mínimos
export type Source = (typeof demo.sources)[number];
export type EventItem = (typeof demo.events)[number];
export type Proposal = (typeof demo.proposals)[number];
export type InboxItem = (typeof demo.inbox)[number];
export type Approval = (typeof demo.approvals)[number];

export const fixtures = demo;

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
export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    timeZone: "America/Sao_Paulo"
  });
}
