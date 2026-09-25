# Matriz — G4

Comandos na worktree `jarvis-g4-execucao-supervisionada`.

| Comando | Quando | Resultado |
|---|---|---|
| `uv run --locked pytest -q` | baseline | 157/157 |
| `npm test`, typecheck, lint | baseline | 64/64, PASS, PASS |
| `JARVIS_E2E_SCREENSHOT_DIR=/tmp/jarvis-g4-baseline-captures npm run e2e` | baseline | 36/36 |
| `uv run --locked pytest -q` | depois do G4 | **159/159** (157 anteriores mais corrupção estável e SIGKILL/resume) |
| `npm test` | depois do G4 | **64/64** |
| `npm run typecheck` e `npm run lint` | depois do G4 | PASS |
| `JARVIS_E2E_SCREENSHOT_DIR=/tmp/jarvis-g4-final-captures npm run e2e` | depois do G4 | **38/38** (36 anteriores mais o painel API em desktop e mobile) |

O teste `test_sigkill_during_open_step_requires_authorized_resume` mata só o `serve.py` de teste na porta 18771, no arquivo temporário do pytest, depois que `JARVIS_TEST_PAUSE_FILE` contém `open`.

## R1 — cancelamento e revogação

Worktree `jarvis-g4-r1-cancel-revoke`, derivada de `78d4e882a5f3f3745805025eb22d04349e2ca0a6`. O commit G4 não foi reescrito.

| Comando | Resultado |
|---|---|
| `uv run --locked pytest -q` | **167/167** |
| `npm test` | **64/64** |
| `npm run typecheck` e `npm run lint` | PASS |
| `npm run build` | PASS |
| `JARVIS_E2E_SCREENSHOT_DIR=/tmp/jarvis-r1-e2e-captures npm run e2e` | **38/38**, exit 0 |

Os probes novos estão em `apps/api/test_mission_engine.py`. Portas 18791–18798, bancos em diretório `0700` do pytest. O cenário que antes deixava a etapa gravar depois do cancelamento agora termina em HTTP 409, missão `cancelled` e zero artefatos. O cenário da revogação termina em HTTP 403, missão `interrupted` e zero artefatos.
