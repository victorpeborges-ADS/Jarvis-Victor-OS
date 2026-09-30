# R6 — Matriz de verificação

## Resultado da candidata

| Verificação | Resultado | Evidência/observação |
|---|---:|---|
| API integral com Python 3.12 e `uv run --locked pytest -q` | PASS — 285 testes | Inclui regressões R1–R5, migrações/idempotência, segurança local, grants/revogação, backup/restore, review, knowledge e os 19 probes R6 |
| Direcionados R6/R5, sources e knowledge | PASS — 60 testes | `test_r6_combined_tampering.py`, `test_r5_trusted_state.py`, `test_selected_source_api.py`, `test_knowledge_api.py` |
| Vitest | PASS — 66 testes em 15 arquivos | `npm test` |
| TypeScript | PASS | `npm run typecheck` |
| ESLint | PASS, sem avisos | `npm run lint`; Next.js avisa que `next lint` será removido no Next.js 16 |
| Build web | PASS | Next.js 15.5.26; páginas estáticas geradas |
| E2E rodada 1 | PASS — 64; 2 skips intencionais; 0 retries | 66 casos descobertos; detalhes dos skips abaixo |
| E2E rodada 2 | PASS — 64; 2 skips intencionais; 0 retries | Rodada integral repetida após a API final; detalhes dos skips abaixo |
| Visual/responsivo | PASS | Playwright verificou 320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px nas oito rotas de produto |
| `git diff --check` contra R5 e main | PASS | SHA de base R5 e main informada |
| `git fsck --full` | PASS | Sem erros; havia objetos dangling anteriores no preflight |

## Regressão API coberta

A execução integral inclui os módulos de backup/restore, store/migrações e idempotência 0013, reconciliação 0014/0015, curated source admission e quarantine, source proof, decisão importada, stale review, staged knowledge e aprovação separada, aprovação de artefatos, transições/cancelamento, corridas read/reconcile, mission read/write/review revoke, owner/domain isolation, separação DEMO/API, rollback/retry, restart, `integrity_check` e `foreign_key_check`.

Os probes de lock exercitam ambas as ordens (`read → reconcile` e `reconcile → read`) sem deadlock. R6 não cria migração.

## Skips E2E

Em cada rodada, 66 casos foram descobertos: 64 executados com sucesso e 2 ignorados intencionalmente, um por projeto. `QA visual noturna: dez larguras...` roda apenas no projeto desktop; `navegação mobile Mais...` roda apenas no projeto mobile. O teste `R5 approval label...` e o QA noturno exercitam os dez tamanhos também entre os projetos. Portanto, nenhum skip foi contado como PASS e ambos refletem escopo explícito de projeto, não teste quebrado.

## E2E e captura

Comando oficial usado duas vezes: `npm run e2e -- --retries=0`. O script fez build novo, criou SQLite sintético temporário, iniciou o runner oficial `uv run --locked python serve.py` em loopback e removeu o diretório temporário ao encerrar.

A primeira tentativa de preparação antes das rodadas não iniciou os serviços: `spawn uv ENOENT` (exit 1), pois `uv` não estava no PATH do host. O executável foi disponibilizado temporariamente em `/tmp` e as duas rodadas completas seguintes terminaram com exit 0. Nenhum serviço persistente foi instalado.

Os dois skips por rodada e as advertências de depreciação do `httpx`/Starlette foram registrados; não houve retry. Capturas finais da inspeção visual: `captures/R6_mobile_320px.png`, `R6_mobile_390px.png`, `R6_mobile_767px.png`, `R6_desktop_768px.png`, `R6_desktop_769px.png`, `R6_desktop_1024px.png` e `R6_desktop_1440px.png`.
