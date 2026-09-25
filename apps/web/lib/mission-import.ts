import type { Mission } from "@/lib/mission-contracts";
import { isMission } from "@/lib/mission-validation";

export interface ImportQuarantine {
  index: number;
  reason: string;
}

/** Classify browser records before any server call. Invalid items never leave the client as accepted. */
export function planMissionImport(records: unknown[]): { accepted: Mission[]; quarantined: ImportQuarantine[] } {
  const accepted: Mission[] = [];
  const quarantined: ImportQuarantine[] = [];
  const seen = new Set<string>();
  records.forEach((record, index) => {
    if (!isMission(record)) {
      quarantined.push({ index, reason: "contrato inválido" });
      return;
    }
    if (!record.domain_id) {
      quarantined.push({ index, reason: "domínio ausente; DEMO e API não são misturados" });
      return;
    }
    if (seen.has(record.id)) {
      quarantined.push({ index, reason: "identificador repetido" });
      return;
    }
    seen.add(record.id);
    accepted.push(record);
  });
  return { accepted, quarantined };
}
