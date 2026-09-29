# R5 — Matriz de verificações

Os comandos abaixo devem ser executados na worktree R5. Não rode Playwright diretamente; `npm run e2e` prepara o backend sintético temporário e o build descartável.

## Backend

| Área | Cobertura | Comando |
|---|---|---|
| Prova de fonte | fixture desconhecida, bytes/hash divergentes, catálogo, snapshot ausente/alterado, referência, domínio, knowledge review e owner/mission | `cd apps/api && uv run --locked pytest -q test_r5_trusted_state.py` |
| Corrida/restart/backup | leitura↔reconciliação, restart, backup/restore e quarentena | incluído em `test_r5_trusted_state.py` |
| Decisão importada | cinco strings de autoridade, importação neutra, replay, ledger contraditório e principal distinto | incluído em `test_r5_trusted_state.py` |
| Migração | pre-G4, G4, G5, R2-0013, R3 pré-0014, fixture exata e desconhecida | `cd apps/api && uv run --locked pytest -q test_memory_store.py test_selected_source_api.py` |
| Regressão API | contratos, auth, revogação, G4/G5/R2/R3/R4/R5 | `cd apps/api && uv run --locked pytest -q` |

## Web e dispositivo móvel

| Checagem | Comando/escopo |
|---|---|
| Unitários | `cd apps/web && npm test` |
| Tipos | `cd apps/web && npm run typecheck` |
| Lint | `cd apps/web && npm run lint` |
| Build | `cd apps/web && npm run build` |
| E2E desktop + mobile, sem retry | `cd apps/web && npm run e2e -- --retries=0` — repetir duas vezes |
| Layout adaptativo | 320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px; verificar labels da navegação, overflow horizontal, alvos e foco |

## Evidência executada durante implementação

- `cd apps/api && uv run --locked pytest -q`: **265 passed, 2 warnings**, em 56,14 s.
- Probes direcionados de proveniência, migração, revisões, conhecimento, revogação e sessão (`test_r5_trusted_state.py`, `test_memory_store.py`, `test_selected_source_api.py`, `test_review_api.py`, `test_knowledge_api.py`, `test_mission_read_revocation_races.py`, `test_mission_auth_races.py`, `test_mission_import_identity.py`, `test_local_security.py`): **177 passed, 2 warnings**, em 32,16 s.
- Vitest: **66 passed** em 15 arquivos.
- `npm run typecheck`, `npm run lint` e `npm run build`: **PASS**; lint sem avisos/erros. Next.js reporta apenas que `next lint` será removido na versão 16.
- Mobile: Vitest **2 passed**, lint e build **PASS**.
- `npm run e2e -- --retries=0`: duas rodadas com **64 passed e 2 skips esperados por projeto**, sem retries.
- E2E verificou layout sem overflow nos 10 breakpoints listados, em projetos desktop e mobile. As capturas em `captures/round-1/` e `captures/round-2/` registram todas as larguras.
- `git diff --check` comparando com R4 e main: **PASS**, sem erros.
