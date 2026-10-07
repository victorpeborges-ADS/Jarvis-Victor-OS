# MAC-003.1.1 — precisão temporal e evidência WebView

07/10/2026, America/Sao_Paulo. Candidata para reauditoria; não constitui aceite formal.

## BASELINE, objetivo e referências preservadas

- BASELINE: `0bfd80f4e69243dcf50375552a135304576ee354`.
- Nova branch: `feat/jarvis-g6-mac-003-1-1-temporal-webview`.
- Nova worktree: `/Users/vic/.codex/worktrees/jarvis-mac-003-1-1-temporal-webview/Jarvis-Victor-OS`.
- SHA da entrega: commit que contém este relatório, consultável com `git rev-parse HEAD` na nova branch.
- Candidata auditada preservada: `feat/jarvis-g6-mac-003-1-close-p2` no SHA BASELINE.
- `main` preservada: `bf575be1645578eebedd41cddd3463b75726776b`.
- OBJETIVO: eliminar descarte prematuro por truncamento de segundos, verificar os limites temporais e registrar o estado real do smoke Tauri/WebView.

## Correção e decisões

O servidor continua autoritativo: as mesmas guardas de `local_security.py` validam sessão/grant antes de cada leitura. Não houve mudança de autorização, TTL, tolerância ou scheduler.

A API nativa agora transmite `expires_at_epoch_us`, inteiro exato em microssegundos para sessão e grant. O cálculo usa a diferença de datetimes UTC e aritmética inteira de dias/segundos/microssegundos; não usa float ou `int(timestamp())`. A expiração ISO `expires_at` continua sendo a mesma, sem arredondamento da validade.

Rust armazena e compara instantes em microssegundos. Grant ativo continua no cache até o instante preciso; `now >= deadline` limpa o grant, e sessão expirada limpa ambos. Nenhuma janela de tolerância mantém leitura além da validade do servidor. A leitura sempre segue para revalidação na API; o cache não concede autorização sozinho.

O DTO textual privado de aplicação exige o novo campo exato. Cliente/servidor nativos desta candidata devem ser usados juntos; o parser estrito recusa envelopes antigos com `expires_at_epoch`. Isso não altera handshake, HMAC, versão de transporte, allowlist de rotas, supervisor ou garantias MAC-002. A WebView continua recebendo estado e ISO de validade, sem tokens ou o novo epoch privado.

## Arquivos alterados

- `apps/api/native_app_api.py`: representação exata da expiração de sessão/grant.
- `apps/api/test_native_app_api.py`: assertions do novo campo e regressões fracionárias determinísticas.
- `apps/desktop/src-tauri/src/runtime_manager.rs`: precisão do cache/relógio e regressão determinística Rust.
- `docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md`: campo e unidade explícitos.
- Este relatório.

Nenhuma mudança em `local_security.py`, handshake, `native_runtime.py`, `serve.py`, `transport.rs`, migrations, contratos SQLite, manifests ou lockfiles. Sem instalação/atualização de dependências, merge, push, tag ou deploy.

## Testes determinísticos e resultados

No servidor, o relógio é injetado em `local_security` e no adapter nativo. A criação tem fração `.750000`; a resposta preserva essa fração em microssegundos para sessão e grant. O teste cria apenas uma missão fictícia em SQLite temporário.

| Instante relativo ao prazo autoritativo | Rust/cache | Servidor: leitura | Novo consentimento |
|---|---|---|---|
| 750 ms antes (ponto em que o truncamento antigo descartava o cache) | grant ativo | permitida | conflito legítimo: o grant ainda está ativo |
| 1 µs antes | grant ativo | permitida | conflito legítimo: o grant ainda está ativo |
| limite exato | grant descartado | negada | sucesso, novo grant/ID, nova leitura permitida |

O teste API compara o inteiro transmitido ao datetime exato. O teste Rust usa o parser de envelope, uma expiração em `1_750_000` µs, mantém o grant em `1_000_000` e `1_749_999`, e o descarta em `1_750_000`. Também verifica sessão 1 µs antes e no limite. Não usa sleep para modelar a passagem do prazo. Não há conflito **obsoleto** na renovação: durante a janela antiga de 750 ms o cache mantém o grant e não apresenta concessão ausente; no limite em que o cache o descarta o servidor permite renovação. Uma tentativa duplicada antes da validade terminar continua corretamente recusada.

A regressão de isolamento/expiração da sessão anterior e a integração Rust → UDS → FastAPI verificam que a mudança de unidade não quebra sessão, grant, leitura, revogação repetida, fechamento com grant ativo e nova sessão sem herança. Esses testes não são smoke da WebView.

## Comandos executados

Comandos abaixo executados com prefixo `rtk`, omitido na tabela para legibilidade. Sem rerun da suíte inteira: evidências anteriores permanecem em `MAC_003_1_CLOSE_P2_REPORT.md`.

As dependências locais já existentes foram reutilizadas: o lock Python e o lock npm foram comparados com os da candidata e eram idênticos; o ambiente Python e `node_modules` foram referenciados por links locais ignorados pelo Git. Não foram usados `npm install`, `npm ci`, `uv sync` ou downloads de crates. Cargo executou com `--locked --offline`.

| Comando | Resultado |
|---|---|
| `.venv/bin/python -B -m pytest -p no:cacheprovider test_native_app_api.py test_mission_auth_races.py test_mission_read_revocation_races.py -q` | PASS: 29 testes, 1 warning herdado TestClient/HTTPX |
| `cargo test --locked --offline runtime_manager::tests::fractional_grant_deadline_keeps_750ms_and_expires_without_grace -- --exact` | PASS: 1 teste, 82 filtrados |
| `cargo test --locked --offline runtime_manager::tests::cached_grants_follow_session_identity_and_exact_expiry_boundary -- --exact` | PASS: 1 teste, 82 filtrados |
| `cargo test --locked --offline runtime_manager::tests::rust_manager_uses_fastapi_g5_over_authenticated_uds -- --exact` | PASS: 1 teste, 82 filtrados; STOP/reap e limpeza UDS |
| `node --test tests/runtimeCommand.test.mjs` | PASS: 4 testes; invoke substituto, não IPC da janela |
| `npm run build` | PASS: TypeScript + Vite |
| `npm run tauri -- build --no-bundle -- --locked --offline` | PASS: release otimizado em 4m44s; executável `apps/desktop/src-tauri/target/release/desktop`; frontend final PASS |
| `cargo fmt` e `cargo fmt --check` | PASS |
| `git diff --check` | PASS |
| `git diff --exit-code BASELINE -- apps/api/local_security.py apps/api/serve.py apps/api/native_runtime.py apps/desktop/src-tauri/src/transport.rs apps/api/uv.lock apps/desktop/src-tauri/Cargo.lock apps/desktop/package-lock.json` | PASS; arquivos preservados |

### Falhas intermediárias e histórico

Nenhum teste ou build falhou nesta rodada; não houve rerun para esconder falhas. A primeira forma de reutilizar `.venv` (link direto na raiz do ambiente) apareceu como não rastreada porque a regra `.venv/` ignora diretórios, não esse link. O link foi removido com `unlink` e substituído por diretório `.venv` ignorado com links internos para `bin`, `lib` e `pyvenv.cfg` existentes. O Python 3.12.14 e os imports foram verificados; nenhuma dependência foi instalada e nenhum arquivo da candidata foi alterado.

As falhas dos sprints anteriores continuam preservadas nos relatórios anteriores; não foram apagadas ou reclassificadas como sucesso desta execução.

## Jornada Tauri/WebView real e capturas — P2 ABERTO

Não executada neste ambiente. Foi oferecida execução manual pelo usuário após preparar o build, sem envio de passphrase/tokens. A resposta explícita foi **“Deixar o P2 aberto neste ambiente”**. Não houve tentativa de `cua.getApp` neste sprint, substituição por browser, automação AppleScript, eval injetado ou apresentação de wrappers como smoke real.

| Passo na janela Tauri/WebView | Resultado |
|---|---|
| Abrir sessão sintética | BLOCKED / não executado |
| Consentir `mission:read` | BLOCKED / não executado |
| Listar missão sintética e verificar DTO IPC | BLOCKED / não executado |
| Revogar e confirmar leitura negada | BLOCKED / não executado |
| Fechar/reabrir sessão e confirmar ausência de grant herdado | BLOCKED / não executado |

Não houve captura visual, registro de resultado manual nem observação dos comandos IPC/DTOs nessa janela. Nenhuma passphrase ou token foi registrado no relatório. O build nativo, se bem-sucedido, comprova compilação e não fecha este P2.

## Processos e listeners residuais

Verificação final por `pgrep -f` limitada ao runner e aos binários desktop/helpers desta worktree: nenhum processo residual. A árvore de build anteriormente sob PID 66004 também terminou. Sem processos desses runtimes ou build, não há listener residual atribuível a eles. Nenhum listener de outras aplicações foi encerrado. Não foram iniciados Vite dev server, janela Tauri para smoke, túnel ou listener público. Os testes API usam TestClient e banco temporário; a integração Rust/FastAPI completou STOP/reap de seu único filho e limpeza do UDS.

## Riscos residuais, autorização e próximo gate

- P2 do smoke Tauri/WebView real permanece aberto por falta de evidência e pela resposta explícita do usuário.
- Cliente/servidor privados precisam corresponder ao novo envelope de microssegundos; versões antigas são recusadas pelo parsing estrito.
- Garantias de sessão/grant continuam locais, voláteis e de processo único. Sem extensão para dados reais ou fontes externas.
- Vulnerabilidade herdada `source-map-js` e warnings anteriores não foram tratados ou reauditados: dependências fora do escopo e preservadas.
- Nenhuma pendência de autorização para a correção local. Sem solicitação de autorização para deploy ou fontes externas.
- Próximo gate: reauditoria independente desta branch/commit e, em ambiente apropriado, registro do smoke real antes de fechar o P2 restante. Nenhum aceite formal declarado.
