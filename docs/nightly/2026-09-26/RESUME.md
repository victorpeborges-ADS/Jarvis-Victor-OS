# Retomar a operação

**Worktree exclusiva:** `/Users/vic/.codex/worktrees/jarvis-overnight-unified-2026-09-26/Jarvis-Victor-OS`. Branch `feat/jarvis-overnight-unified-2026-09-26`, base G5 congelada `4931c56d107f49e01d677c097ef33ceb5618015f`. Implementação até `2b79940`; consulte `git rev-parse HEAD` para o commit documental posterior. Não tocar na `main`, checkout original ou candidata G5. Não push/merge/tag sem nova autorização.

**Últimas migrações:** 0010 snapshots/ledger G5, 0011 decisões de conhecimento, 0012 fontes sintéticas escolhidas. Banco E2E temporário. Sessões/grants reiniciam ao parar API; dados de Missão persistem somente no banco especificado. O processo de E2E deve encerrar sua API/Next ao terminar; o PID 41686 do smoke macOS foi encerrado. Verifique portas 3000/8000 antes de novos testes.

**Testes validados:** `apps/api: uv run --locked pytest -q` 197 PASS; `apps/web: npm test -- --run`, `npm run typecheck`, `npm run lint`, `npm run build` PASS; E2E completo **54 PASS/2 SKIP em duas rodadas consecutivas após `2b79940`**, sem retries; botão de concessões e arquivo fictício 2 PASS cada. Mobile web 2 unit + 4 E2E, build/lint/cap sync PASS; Gradle exit 1 sem Java. `.app` construído e smoke PASS; APK ausente.

**Comandos úteis, sempre na worktree:**

```bash
cd apps/api && uv sync --locked --python 3.12 && uv run --locked pytest -q
cd apps/web && npm test -- --run && npm run typecheck && npm run lint && npm run build
cd apps/web && JARVIS_E2E_SCREENSHOT_DIR=/Users/vic/.codex/worktrees/jarvis-overnight-unified-2026-09-26/Jarvis-Victor-OS/exports/nightly/2026-09-26/captures npm run e2e
python3 docs/nightly/2026-09-26/generate_manifest.py
git -c core.whitespace=cr-at-eol diff --check
```

`npm run e2e` é o runner oficial: cria banco descartável e inicia API pelo `serve.py`; não executar `npx playwright test` diretamente. Para demo manual, siga `DEMO_GUIDE.md`. Para o `.app`, `open -n -a` no caminho de `CLIENT_BUILD_MATRIX.md`; shell offline. Android precisa de JDK/SDK e licenças antes de `cd apps/mobile/android && ./gradlew assembleDebug`.

**Próxima revisão:** auditor independente do snapshot noturno; corrigir findings reais, depois solicitar aceite/merge. SDK nativo, MCP, conectores e nuvem ainda não implementados; status em `CONNECTOR_CAPABILITIES.md` e `APPROVAL_REQUESTS.md`.
