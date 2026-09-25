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
