# Matriz de testes — sprint JARVIS

## Ambiente

- macOS Darwin, Node `v26.7.0`, npm `11.19.0`, uv `0.12.13`, Python do projeto `3.12.14`, pytest `9.0.3`, Next `15.5.26`, Vitest `5.0.1`.
- Worktree isolada e branch `feat/jarvis-nightly-2026-09-25-042315`.
- `127.0.0.1:3000` estava em uso por outro workspace (PID 48315). O processo foi somente identificado e não foi alterado. Testes E2E passaram em `[::1]:3000` com API `[::1]:8000`.

## Resultados

| Comando/ação | Resultado | Cobertura/evidência |
|---|---|---|
| `npm ci` em `apps/web` | **PASS** | Instalação limpa do lockfile. |
| `uv sync --locked --python 3.12` em `apps/api` | **PASS** | Dependências sincronizadas para Python fixado do projeto. |
| `rtk uv run --locked pytest` em `apps/api` | **PASS — 146/146** | `test_backup_recovery`, `test_calendar_simulator`, `test_contract`, `test_local_security`, `test_main`, `test_memory_store`, `test_mission_contracts`. 2 avisos de depreciação Starlette/httpx e uso de cookies por requisição. |
| `rtk npm test` em `apps/web` | **PASS — 53/53** | 12 arquivos; inclui contratos, missões, ciclo do conhecimento, contexto, router e observadores. |
| `rtk npm run typecheck` | **PASS** | `tsc --noEmit`. |
| `rtk npm run lint` | **PASS** | Sem warnings/erros ESLint; `next lint` avisa que será removido no Next 16. |
| `rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' npm run e2e` | **PASS — 32/32** | Desktop e mobile, Chromium; build de produção incluído; API em banco SQLite sintético temporário fora do repo. Gate E browser, journeys Gate 1, drawer/a11y e fluxo de Missões. |
| Mesma origem acima com `-- --project=mobile --grep 'missão sintética'` | **PASS — 1/1** | Captura mobile revisada após tirar elementos sticky apenas no screenshot. |
| Mesma origem acima com `-- --project=desktop --grep 'missão sintética'` | **PASS — 1/1** | Captura desktop revisada após tirar elementos sticky apenas no screenshot. |
| `rtk npm run e2e` sem origem IPv6 | **BLOCKED no pré-voo** | Runner detectou `127.0.0.1:3000` ocupado e saiu antes de build/API. Não é resultado da suíte nem falha de produto; evitou usar servidor alheio. |
| E2E em portas alternativas não allowlisted | **RECUSADO conforme contrato** | A interface web abriu, mas login recebeu recusa de Origin; 24 casos DEMO passaram, 4 integrados não puderam autenticar. Não contar como defeito nem como aprovação do fluxo integrado. |
| `rtk git diff --check` | **PASS** | Antes de commits de código e no fechamento do pacote documental. |
| `rtk npm install && rtk npm run build` em `apps/desktop` | **PASS** | React/Vite frontend compilou; `npm audit` reportou zero vulnerabilidades. Não executa Cargo/Tauri nativo. |
| `rtk npm test` em `apps/mobile` | **PASS — 2/2** | Outbox sintética: limite de 20, texto máximo, JSON inválido e marcador sintético obrigatório. |
| `rtk npm run lint && rtk npm run build` em `apps/mobile` | **PASS** | Oxlint limpo; TypeScript e Vite compilados. |
| `rtk npm run e2e` em `apps/mobile` | **PASS — 4/4** | Playwright usa Vite loopback `127.0.0.1:5173`; navegação, gravação em outbox e reload em viewports desktop/mobile, sem requisições externas. |
| `rtk npx cap add android && rtk npx cap sync android` | **PASS** | Estrutura Android gerada e assets copiados; nenhuma compilação Gradle foi disparada. |
| `rtk npm audit` em `apps/mobile` | **PASS — 0 vulnerabilidades** | CLI Capacitor ficou em `8.4.3` (major 8) depois do conjunto inicial indicar advisory moderado transitivo por `uuid`/`xcode`; versão inicial substituída sem `--force`. |
| Tauri/Cargo e Capacitor/APK nativos | **BLOCKED / NÃO TESTADO** | `rustc`, Cargo, Android SDK/Studio, Gradle e `adb` ausentes; nada foi instalado. `.app` e APK não foram gerados. |
| Hosting cloud, billing, LLM, n8n, OAuth e dados reais | **NÃO TESTADO / NÃO EXECUTADO** | Nenhuma conta, credencial, chamada externa ou recurso de cloud criado. |
| Socket em interface pública e teste físico de DNS rebinding | **NÃO TESTADO** | Probes só via ASGI TestClient e inspeção dos guards. Um listener público seria fora do escopo permitido. |
| Revisão exaustiva de logs/tracebacks inesperados | **NÃO TESTADO** | Access log do Uvicorn está desligado e os handlers testados são genéricos; não foi feita revisão operacional completa. |

## Probes adversariais incluídos nas suítes

- Sessão ausente, forjada, expirada, logout, reload do browser e token antigo em novo processo: `apps/api/test_local_security.py:224-252`; E2E `apps/web/e2e/integration.spec.ts:194-219`.
- Cookie `HttpOnly`/`SameSite`/`Secure`, passphrase Unicode e erro de validação sem reflexão: `apps/api/test_local_security.py:205-222,296-314`.
- CSRF ausente, inválido, de outra sessão e Origin externa cruzados por cinco operações, sem mutação: `apps/api/test_local_security.py:334-384`.
- Grants expirados, duplicados, conflitantes, revogados; leitura agregada, briefing, domínio divergente e ID direto: `apps/api/test_local_security.py:463-538`.
- Host/DNS rebinding simulado, origem externa, `docs`, OpenAPI e cliente/servidor não loopback: `apps/api/test_local_security.py:386-411`.
- Migração com rollback, DB/schema/índice inválido, colisão de IDs e restauração backup sem plaintext: `apps/api/test_memory_store.py:97-225,401-435,555-605`; `apps/api/test_backup_recovery.py:87-141,246-264`.
- Revogação durante Calendar sync antes do commit, após commit/antes da resposta e durante reconciliação paginada; stale 24 h: `apps/api/test_calendar_simulator.py:317-331,430-486,489-575,679-733`.
- Missão: zero chamadas `/real/`, persistência por reload, evidências, revisão local, retry e cancelamento: `apps/web/e2e/missions.spec.ts:7-64`.
