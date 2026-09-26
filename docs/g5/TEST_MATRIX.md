# Matriz de Testes — G5

Comandos executados na worktree `jarvis-g5-aprovacao-persistente`.

| Suíte | Quando | Resultado | Detalhes |
|---|---|---|---|
| `uv run --locked pytest -q` | baseline | 167/167 | exit 0 |
| `npm test` (Vitest) | baseline | 64/64 | exit 0 |
| `npm run typecheck` | baseline | PASS | exit 0 |
| `npm run lint` | baseline | PASS | exit 0 |
| `npm run build` | baseline | PASS | exit 0 |
| `npm run e2e` | baseline | 40/40 | exit 0 |
| `uv run --locked pytest -q` | pós-G5 | **178/178** | exit 0 (+11 novos testes de autorização, banco e revisão) |
| `npm test` (Vitest) | pós-G5 | **66/66** | exit 0 (+2 testes de cliente de revisão) |
| `npm run typecheck` | pós-G5 | **PASS** | exit 0 |
| `npm run lint` | pós-G5 | **PASS** | exit 0 |
| `npm run build` | pós-G5 | **PASS** | exit 0 |
| `npm run e2e` (Rodada 1) | pós-G5 | **42/42** | exit 0 (desktop + mobile, sem retries) |
| `npm run e2e` (Rodada 2) | pós-G5 | **42/42** | exit 0 (desktop + mobile, sem retries) |
| `G4-R1 Probes Críticos` | pós-G5 | **2/2** | exit 0 (`test_cancel_confirmed_before_skill_prevents_artifact`, `test_revoked_write_grant_before_commit_requires_new_grant_to_resume`) |
| `git diff --check` | pós-G5 | **0** | limpo com `core.whitespace=cr-at-eol` |

## Probes adversariais executados

1. **Permissão de revisão isolada**: sem grant `mission:review`, decisão responde 403. Concessão apenas de `mission:write` ou de Calendar não autoriza.
2. **Replay idempotente**: mesma chave e mesmo corpo devolve a decisão persistida com `replayed: true`. Mesma chave com corpo diferente responde 409.
3. **Decisões concorrentes**: duas decisões concorrentes sobre a mesma revisão linearizam via SQLite `BEGIN IMMEDIATE`; exatamente uma vence (200) e a outra recebe 409.
4. **Isolamento entre principais**: principal `owner_b` recebe 404 ao consultar ou tentar decidir sobre artefato do `owner`.
5. **Revogação sob pausa (falha fechada)**: revogação da concessão `mission:review` durante o checkpoint de pausa impede a decisão, responde 403 e deixa zero novas linhas ou alterações no banco.
6. **Ajustes e versionamento**: decisão `changes_requested` exige motivo (sem motivo -> 422). Submissão de conteúdo revisado cria versão 2 em estado `pending`, mantendo a versão 1 em `changes_requested`. Aprovação da versão 2 não afeta a imutabilidade da versão 1.
7. **Missão cancelada**: tentativa de decidir revisão em missão com status `cancelled` responde 422.
8. **Sobrevivência a reinício forçado e backup cifrado**: reinício da API e restauração de backup cifrado preservam integralmente o estado da revisão, histórico e eventos.
