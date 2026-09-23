import { fixtures } from "@/lib/demo";

export type DomainId = (typeof fixtures.domains)[number]["id"];

export type DomainScoped = {
  domain_id?: string | null;
};

const KNOWN = new Set(fixtures.domains.map((d) => d.id));

/** Identificador explícito. Título, sensibilidade e proveniência não contam. */
export function isKnownDomainId(domainId: string | null | undefined): domainId is DomainId {
  return typeof domainId === "string" && KNOWN.has(domainId as DomainId);
}

export function domainName(domainId: string | null | undefined): string {
  const found = fixtures.domains.find((d) => d.id === domainId);
  return found?.name ?? "sem domínio";
}

/**
 * Filtro por domínio. Id desconhecido ou ausente devolve lista vazia — sem lançar.
 * Não há compartilhamento: só entra quem tem exatamente esse domain_id.
 */
export function recordsForDomain<T extends DomainScoped>(records: readonly T[], domainId: string): T[] {
  if (!isKnownDomainId(domainId)) return [];
  return records.filter((record) => record.domain_id === domainId);
}

export function partitionByDomain<T extends DomainScoped>(records: readonly T[]): {
  assigned: T[];
  unassigned: T[];
} {
  const assigned: T[] = [];
  const unassigned: T[] = [];
  for (const record of records) {
    if (isKnownDomainId(record.domain_id)) assigned.push(record);
    else unassigned.push(record);
  }
  return { assigned, unassigned };
}

export function countForDomain(domainId: string, events = fixtures.events, captures: DomainScoped[] = fixtures.inbox): number {
  return recordsForDomain(events, domainId).length + recordsForDomain(captures, domainId).length;
}
