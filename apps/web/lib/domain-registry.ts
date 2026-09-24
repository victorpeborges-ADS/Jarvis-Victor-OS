import { fixtures } from "@/lib/demo";

export type DomainId = (typeof fixtures.domains)[number]["id"];

const KNOWN = new Set(fixtures.domains.map((domain) => domain.id));

/** Registro canônico. Não consulta título, sensibilidade nem proveniência. */
export function isKnownDomainId(domainId: unknown): domainId is DomainId {
  return typeof domainId === "string" && KNOWN.has(domainId as DomainId);
}

export function domainName(domainId: string | null | undefined): string {
  return fixtures.domains.find((domain) => domain.id === domainId)?.name ?? "sem domínio";
}
