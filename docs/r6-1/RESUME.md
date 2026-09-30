# JARVIS R6.1 — resumo de handoff

- Baseline: R6 `5bd2dd74a35793bf3356fe3b754b34fa21a126cb`.
- Branch: `feat/jarvis-unified-r6-1-knowledge-provenance`.
- Objetivo: exigir prova positiva para cada origem suportada de knowledge.
- Causa: a projeção anterior tratava a ausência de elo de selected source como suficiente para aceitar outra claim de `kind`, permitindo que conteúdo adulterado fosse exposto como `staged`.
- Mudança: `resolve_trusted_knowledge_projection` exige cadeia relacional completa de `selected_original` ou reprodução verificável de `skill_derived`; qualquer claim sem prova fecha em quarentena.
- Schema: sem migração. Conhecimento legado sem registros suficientes continua persistido, retido e auditável.
- UI: proveniência vem somente da projeção positiva da API; itens sem prova são rotulados “Origem não verificada” e têm conteúdo retido.
- Evidência: veja `RELATORIO_R6_1.md`, `KNOWLEDGE_PROVENANCE.md`, `KNOWLEDGE_TAMPERING_MATRIX.md` e `TEST_MATRIX.md`.

> G5 permanece sem aceite formal. R6.1 fecha exclusivamente a proveniência positiva de knowledge e não altera a fronteira de confiança ADR-010.
