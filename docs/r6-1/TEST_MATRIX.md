# R6.1 — Matriz de testes

## Testes dirigidos

| Escopo | Comando/módulo | Evidência coberta |
|---|---|---|
| Reprodução independente do P1 | `apps/api/test_knowledge_provenance.py::test_selected_knowledge_detached_as_skill_derived_is_quarantined_everywhere` | Bytes adversariais retidos em knowledge, missão, fontes, review, decisão, contexto, build-context e conclusão |
| Prova positiva do fluxo derivado | `apps/api/test_knowledge_provenance.py::test_legitimate_skill_derived_knowledge_needs_approved_source_review` | Origem staged verificável, aprovação da review, aprovação independente do knowledge e inclusão em contexto |
| 20 adulterações | `apps/api/test_knowledge_provenance.py::test_unproven_knowledge_tampering_matrix_fails_closed` parametrizado | Casos explícitos em `KNOWLEDGE_TAMPERING_MATRIX.md`, com prova direta, projeção API e integridade FK |
| Provas relacionais existentes | `apps/api/test_selected_source_api.py`, `test_r6_combined_tampering.py` | Full relational proof, 19 ataques R6, fontes curated e quarentena |
| Estados e ledger | `apps/api/test_r5_trusted_state.py`, `test_knowledge_api.py`, `test_knowledge_provenance.py` | Importação, review stale, ledger, staged/approval/context, isolamento e reconciliação |
| Migrações e armazenamento | `apps/api/test_memory_store.py` | Migrações 0014/0015, retry/rollback, backup/restore, restart, integridade e FK |
| Autorização e corridas | `apps/api/test_mission_auth_races.py`, `test_mission_read_revocation_races.py`, `test_review_api.py` | Cancel/run_next e revogações de read/write/review na ordem de locks existente |
| Interface | `apps/web/__tests__/knowledge-origin.test.ts` e `apps/web/e2e/audit-g5-review-ui.spec.ts` | Kind sem prova nunca recebe rótulo positivo; revisão, conhecimento, contexto e E2E integrado |

## Resultados finais

| Verificação | Resultado/exit code |
|---|---|
| API completa (`uv run --locked pytest -q`) | PASS — 307 passed, 0 failed, exit 0; 2 deprecation warnings |
| Probes R6.1 + R6/R5 dirigidos | PASS — 70 passed, 0 failed, exit 0; 1 deprecation warning |
| Vitest | PASS — 16 arquivos, 68 testes, exit 0 |
| Typecheck | PASS — exit 0 (reexecutado após evitar concorrência com build) |
| Lint | PASS — sem avisos/erros ESLint, exit 0; aviso de depreciação do `next lint` |
| Build independente | PASS — Next.js 15.5.26, exit 0 |
| E2E rodada final 1, `--retries=0` | PASS — 66 passed, 2 skips previstos, 0 retries, exit 0 |
| E2E rodada final 2, `--retries=0` | PASS — 66 passed, 2 skips previstos, 0 retries, exit 0 |
| Capturas desktop/mobile e larguras | PASS — 320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px; oito rotas sem overflow/sobreposição; inspeção visual concluída |

E2E usa o runner oficial, que compila a web, cria banco temporário e inicia somente a API oficial loopback. Skips são reportados separadamente e não contam como passes.
