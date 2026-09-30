export type KnowledgeOriginType = "selected_original" | "skill_derived" | null;

export function knowledgeOriginLabel(
  originVerified: boolean,
  originType: KnowledgeOriginType,
): string {
  if (!originVerified) return "Origem não verificada";
  if (originType === "selected_original") return "Fixture sintética selecionada";
  if (originType === "skill_derived") return "Derivação por execução verificada";
  return "Origem não verificada";
}
