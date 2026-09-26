# Matriz de testes

Ambiente: macOS Intel; Node 26.7.0, npm 11.19, Python 3.12 via `uv` 0.12.13, Next 15.5.26, Tauri 2. Banco E2E sempre SQLite sintético temporário; API e navegador no mesmo hostname loopback. SHA de implementação testado: `2b79940` mais somente esta documentação. Testes não usam banco padrão nem dados pessoais.

| Escopo | Comando na pasta indicada | Resultado / exit | Observação |
|---|---|---|---|
| Executor | `rtk proxy sh -c 'printf "diag-ok\n"; echo "EXIT_CODE=$?"'` | PASS / 0 | `diag-ok`, `EXIT_CODE=0`. |
| G5 congelado API | `apps/api: uv run --locked pytest -q` | 178 PASS / 0 | Clone destacado, pré-correção. |
| G5 congelado web | `apps/web: npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | 66 PASS / 0 | Duas rodadas E2E 42/42 cada. Probes próprios encontraram FAIL de segurança. |
| API noturna | `apps/api: uv run --locked pytest -q` | **197 PASS / 0** | Migrações 0010–0012, SQLite temporário; inclui 5 novos probes de sessão/grant; 2 warnings de dependência. |
| Web unit | `apps/web: npm test -- --run` | **66 PASS / 0** | 15 arquivos. |
| Web estática | `apps/web: npm run typecheck`; `npm run lint`; `npm run build` | PASS / 0 cada | Build de produção 11 páginas estáticas. |
| Novo fluxo arquivo | `apps/web: npm run e2e -- --grep 'arquivo fictício escolhido'` | **2 PASS / 0** | Desktop e mobile; seleção → duas aprovações → contexto. |
| Web E2E completo 1 | `apps/web: JARVIS_E2E_SCREENSHOT_DIR=.../exports/nightly/2026-09-26/captures npm run e2e` | **54 PASS, 2 SKIP / 0** | Após correção de corrida `2b79940`, sem retries; 2 skips preexistentes por plataforma. |
| Web E2E completo 2 | mesmo comando | **54 PASS, 2 SKIP / 0** | Segunda rodada consecutiva no mesmo código, sem retries. Rodadas anteriores em `6e32973`: 54 PASS/2 SKIP duas vezes. |
| Mobile unit/lint/build | `apps/mobile: npm test -- --run`; `npm run lint`; `npm run build` | 2 PASS e builds PASS / 0 | Shell web, não APK. |
| Mobile E2E | `apps/mobile: npm run e2e` | 4 PASS / 0 | DEMO offline. |
| Capacitor | `apps/mobile: npm exec -- cap sync android` | PASS / 0 | Atualiza projeto Android local, sem APK. |
| Android nativo | `apps/mobile/android: ./gradlew assembleDebug` | **BLOCKED / 1** | Java Runtime ausente; SDK Android ausente. |
| macOS nativo | `apps/desktop: npm run tauri build` com `CARGO_HOME`/`RUSTUP_HOME` temporários | PASS / 0 | `.app` x86_64 gerado; `open -n -a` da versão final exit 0, processo 41686 observado e encerrado. |

Regressões intermediárias registradas: (1) G5 congelado teve achados FAIL apesar de suíte verde; (2) primeira rodada E2E noturna com novos probes 43/46 por preparação duplicada de grant, corrigida; (3) depois da navegação mobile, 49/52 com teste legado buscando link removido, corrigido sem aumentar timeout; (4) E2E novo de arquivo 1/2 ao misturar dois registros com o mesmo conteúdo no banco da rodada, corrigido por filtro de missão. A última rodada direcionada e a primeira rodada completa final passaram.

**Não testado:** conta/OAuth real, dispositivo Android, `.dmg`, notarização, múltiplos processos/usuários reais, performance de carga, zoom visual 200% completo, SDK comum inexistente. Capturas Playwright em `exports/nightly/2026-09-26/captures`; `EXPORTS_MANIFEST.json` lista hashes.
