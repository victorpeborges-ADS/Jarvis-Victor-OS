# R6 — Handoff e retomada

## Estado da candidata

- Branch isolada: `feat/jarvis-unified-r6-2026-09-30`.
- Base obrigatória: `7306093cde4bdfa15b3adfead5e48f1e4d497dad` (R5).
- Nenhuma alteração em main, R5, R4, R3, R2, R1, manutenção `a6cd0fffc4207a10462bef853a8994a8fd037c12` ou checkout compartilhado.
- Pendência organizacional: auditoria independente da R6. G5 permanece sem aceite formal.

## Decisões técnicas

1. A cadeia de fonte é centralizada em `apps/api/source_admission.py::resolve_trusted_source_projection`.
2. Claims persistidas são comparadas a catálogo, snapshot, artefato atual, knowledge e ledger; apenas uma cadeia coerente permite projetar conteúdo confiável.
3. Uma fabricação integralmente coerente do SQLite por administrador é fora da autenticidade do G5 e está explícita em ADR-010 e no probe aprovado de limite.
4. Sem migração R6. Sessões/grants seguem locais e voláteis; não há OAuth, multiworker, API pública nem fontes reais.
5. Interface exibe nome humano de timezone sem alterar `America/Sao_Paulo` usado internamente.

## Ordem dos commits

1. `fix(api): enforce complete relational source proof`
2. `docs(security): define local G5 trust boundary`
3. `fix(web): humanize local timezone label`

O SHA integral da ponta R6 está no handoff final da conversa. Os commits existem somente nesta branch; não houve merge, push ou tag.

## Verificações

Consulte [TEST_MATRIX.md](TEST_MATRIX.md) para os resultados integrais e skips intencionais, [COMBINED_TAMPERING_TESTS.md](COMBINED_TAMPERING_TESTS.md) para a matriz de ataque e [RELATORIO_R6.md](RELATORIO_R6.md) para classificação IMPLEMENTADO/PROVADO/ASSUMIDO/FORA DO ESCOPO.

Na retomada, primeiro confirmar o branch e a ponta R6 em `git status`/`git log`, depois repetir apenas as verificações necessárias. Não partir do shared checkout nem tentar integrar a main sem instrução/autorização separada.

## Declaração

**G5 permanece sem aceite formal. Esta candidata apenas redefine e testa a fronteira de confiança local. Nenhuma integração à main foi realizada.**
