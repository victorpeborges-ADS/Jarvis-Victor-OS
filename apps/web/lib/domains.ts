import { fixtures } from "@/lib/demo";
import { domainName, isKnownDomainId, type DomainId } from "@/lib/domain-registry";
import { parseEvent, parseFixtureCapture, parseLocalCapture, type CaptureRecord } from "@/lib/validate";

export type { DomainId };
export { domainName, isKnownDomainId };

export type DomainScoped = {
  domain_id?: string | null;
};

function asArray(records: readonly unknown[] | null | undefined): readonly unknown[] {
  return Array.isArray(records) ? records : [];
}

type DomainRecord = { id: string; domain_id?: string | null; title?: string };

/**
 * Filtro seguro. Entrada nula, primitiva ou sem domain_id é ignorada.
 * Domínio desconhecido devolve lista vazia, sem lançar.
 */
export function recordsForDomain<T extends DomainRecord = DomainRecord>(
  records: readonly unknown[] | null | undefined,
  domainId: string
): T[] {
  if (!isKnownDomainId(domainId)) return [];
  const out: T[] = [];
  for (const record of asArray(records)) {
    if (!record || typeof record !== "object") continue;
    const id = (record as { domain_id?: unknown }).domain_id;
    if (id === domainId) out.push(record as T);
  }
  return out;
}

export function eventsForDomain(records: readonly unknown[] | null | undefined, domainId: string) {
  if (!isKnownDomainId(domainId)) return [];
  return asArray(records)
    .map(parseEvent)
    .filter((item): item is NonNullable<typeof item> => item?.placement === "assigned" && item.event.domain_id === domainId)
    .map((item) => item.event);
}

export function capturesForDomain(records: readonly unknown[] | null | undefined, domainId: string): CaptureRecord[] {
  if (!isKnownDomainId(domainId)) return [];
  const out: CaptureRecord[] = [];
  for (const record of asArray(records)) {
    const capture = parseLocalCapture(record) ?? parseFixtureCapture(record);
    if (capture?.domain_id === domainId) out.push(capture);
  }
  return out;
}

export function partitionByDomain(records: readonly unknown[] | null | undefined) {
  const assigned = [];
  const unassigned = [];
  for (const record of asArray(records)) {
    const parsed = parseEvent(record);
    if (!parsed) continue;
    if (parsed.placement === "assigned") assigned.push(parsed.event);
    else unassigned.push(parsed.event);
  }
  return { assigned, unassigned };
}

export function countForDomain(
  domainId: string,
  events: readonly unknown[] = fixtures.events,
  captures: readonly unknown[] = fixtures.inbox
): number {
  return eventsForDomain(events, domainId).length + capturesForDomain(captures, domainId).length;
}
