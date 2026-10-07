# MAC-003.1 — fechamento dos P2, candidata para reauditoria

Data: 07/10/2026, America/Sao_Paulo. Não constitui aceite formal.

## BASELINE e objetivo

- Base imutável: `d6e227125e3eb7365f9a58f773e0ae6d67d676a3` (`feat/jarvis-g6-mac-003-g5-vertical`).
- `main` preservada em `bf575be1645578eebedd41cddd3463b75726776b`.
- Nova branch: `feat/jarvis-g6-mac-003-1-close-p2`.
- Worktree: `/Users/vic/.codex/worktrees/jarvis-g6-mac-003-1-close-p2/Jarvis-Victor-OS`.
- SHA da entrega: commit que contém este relatório, consultável com `git rev-parse HEAD` nessa branch.
- Objetivo exclusivo: corrigir o ciclo de vida do grant nativo e verificar a jornada Tauri/WebView real.

## Correção e decisões

Cada grant criado pela API guarda internamente o token da sessão criadora, sem adicioná-lo ao DTO público. Conflitos e revogação são limitados à sessão. A guarda de leitura nativa exige a sessão exata; duas sessões do mesmo principal não compartilham o grant. Sessões novas exigem novo consentimento explícito.

Fechamento e invalidação por expiração revogam os grants e removem a sessão sob o mesmo `RLock` usado pelas guardas de autorização e leitura. A ordem continua autorização → SQLite. Uma leitura que adquiriu o lock antes do fechamento pode concluir seu snapshot; leituras posteriores são negadas. Expiração é observada nas validações e na seleção de grants ativos, sem scheduler ou promessa de limpeza em background. Uma mutação revalida a sessão dentro do lock e também invalida o estado vencido. A varredura remove grants ativos obsoletos antes de novo consentimento.

O cache Rust vincula o grant ao token da sessão, usando `SecretText`; descarta ambos no limite exato da sessão e descarta grant vencido ou de outra sessão. Fechamento fica disponível com grant ativo e limpa ambos após resposta confirmada do servidor. Revogação repetida, inclusive depois de limpar o grant local, permanece idempotente em sessão ativa. Não há abertura automática de sessão nem concessão automática.

A UI permite encerrar a sessão com grant ativo e limpa resultados de missões quando sessão/grant deixam de estar ativos. O consentimento continua explícito. As funções de injeção de testes associam grants sintéticos à única sessão sintética do principal quando existente; isso não é uma rota de produção.

## Arquivos alterados

- `apps/api/local_security.py`: ownership da sessão, invalidação atômica, revalidação, guardas e listagem de grants.
- `apps/api/test_native_app_api.py`: sessões simultâneas, revoke repetido, fechamento, relógio determinístico, conflito obsoleto, revalidação e linearização leitura/fechamento.
- `apps/api/test_local_security.py`: isola `sys.argv` nos dois testes do runner oficial.
- `apps/desktop/src-tauri/src/runtime_manager.rs`: vínculo/expiração do cache, fechamento/revogação e testes Rust/FastAPI.
- `apps/desktop/src/App.tsx`: encerramento disponível e limpeza do resultado sem autorização.
- `docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md`: atualização do lifecycle de sessão/grant, sem mudança do protocolo de transporte.
- Este relatório.

Não foram alterados handshake, framing/HMAC, supervisor MAC-002, migrations, contratos SQLite, manifests ou lockfiles. Nenhum merge, push, tag, deploy ou atualização de dependência.

## Smoke e capturas

### Tauri/WebView real: BLOCKED, P2 permanece ABERTO

A descoberta de superfícies por `cua.getState()` retornou `apps: []`; esta sessão expõe apenas browsers. A tentativa de selecionar o app por `cua.getApp('app.jarvis.desktop')` retornou exatamente `cua.getApp is not a function`. As APIs de controle nativo estão desabilitadas neste ambiente. Não há controle/observação da janela WKWebView nem acesso aos comandos IPC dessa janela por essa ferramenta. Não foi substituída a aplicação por uma aba Chrome, IPC mockado, eval injetado ou AppleScript.

Passos que exigem repetir em ambiente com controle nativo:

| Passo | Resultado na WebView real |
|---|---|
| Iniciar runtime e abrir sessão com credencial sintética | BLOCKED |
| Confirmar consentimento `mission:read` | BLOCKED |
| Listar missão sintética e inspecionar DTO retornado pelo IPC | BLOCKED |
| Revogar e verificar leitura negada, repetir revogação | BLOCKED |
| Consentir novamente, encerrar com grant ativo, abrir outra sessão | BLOCKED |
| Verificar ausência de grant e leitura negada; consentir novamente | BLOCKED |

Nenhuma captura visual da janela foi obtida. O build nativo e testes abaixo não encerram este P2.

### Integração automatizada Rust → UDS → FastAPI: PASS

`rust_manager_uses_fastapi_g5_over_authenticated_uds` prepara SQLite descartável com uma missão fictícia e executa Python 3.12 diretamente como filho. Valida health/version/proof HMAC, credencial recusada sem eco, abertura explícita sem grant, consentimento explícito, listagem com `dataset=api_synthetic`, ausência de tokens/CSRF/ID do grant no JSON retornado, revogação e leitura negada, revogação repetida, novo consentimento, fechamento com grant ativo, nova sessão sem grant/leitura, novo consentimento sem conflito, leitura e fechamento. STOP/reap concluem e o teste remove seu banco e socket temporários. Isso verifica métodos do manager e DTOs em runtime, **não** o invoke Tauri da WebView.

Os testes desktop verificam os seis nomes fixos de IPC e parsers dos DTOs com invoke substituto. Também não são evidência de IPC real na janela.

## Comandos e resultados

Os comandos de validação abaixo foram executados com prefixo RTK, omitido na tabela para legibilidade. Diretórios: raiz, `apps/api`, `apps/desktop` ou `apps/desktop/src-tauri`, conforme o comando.

| Comando | Resultado |
|---|---|
| `uv sync --locked --python 3.12` | PASS; virtualenv novo, versões do lock preservadas |
| `npm ci --ignore-scripts` | PASS; lock preservado; audit reportou vulnerabilidade herdada |
| `uv run --locked pytest test_native_app_api.py test_local_security.py test_missions_api.py test_mission_auth_races.py test_mission_read_revocation_races.py test_native_runtime_process.py -q` (primeira rodada) | FAIL: 80 PASS, 2 FAIL; ver histórico abaixo |
| Mesma regressão após correção do harness | PASS: 82 testes, 2 warnings |
| `uv run --locked pytest -q` | PASS: 316 testes, 2 warnings; coletada antes dos dois últimos testes adicionais |
| `uv run --locked pytest test_native_app_api.py -q` após os dois testes adicionais | PASS: 8 testes; inclui linearização e revalidação no limite de expiração |
| `cargo test --locked` | PASS nas duas rodadas: 73 testes, 9 ignored; segunda rodada inclui limite exato de grant, sessão e troca S1→S2; os ignored incluem helpers executados como processos sintéticos |
| `node --test tests/runtimeCommand.test.mjs` | PASS: 4 testes |
| `npm run build` | PASS: TypeScript + Vite |
| `npm run tauri -- build --no-bundle` | PASS: release otimizado em 4m18s; executável `apps/desktop/src-tauri/target/release/desktop`; frontend final também PASS |
| `cargo fmt --check` | FAIL inicial por formatação; corrigido por `cargo fmt`, depois PASS |
| `git diff --check` | PASS |
| `npm audit --json` | FAIL exit 1: 1 vulnerabilidade high herdada, `source-map-js`, GHSA-68fv-2mgg-jv7q; sem correção de dependências neste sprint |

Teste determinístico Rust: `cached_grants_follow_session_identity_and_exact_expiry_boundary` injeta instantes e verifica antes/no limite da sessão, antes/no limite do grant e troca S1→S2. Não usa sleeps para modelar validade. Os testes de servidor usam relógio injetado e expiração exatamente no limite, grant ainda válido e sessão expirada, incluindo a primeira mutação de novo consentimento sem leitura prévia de S1.

### Histórico de falhas intermediárias

1. A regressão API inicial teve 2 falhas em `test_supported_server_entrypoint_disables_proxy_headers` e `test_supported_entrypoint_rejects_public_bind_before_uvicorn`. Um rerun diagnóstico com `rtk proxy` reproduziu ambas: `serve.main()` recebeu os argumentos do pytest e lançou `SystemExit(64)` antes de chegar ao ramo web. O runner e os testes tinham esse comportamento na candidata; não houve alteração de `serve.py`. O harness agora define somente `serve.sys.argv=["serve.py"]` nesses testes. A segunda regressão focada passou. A falha inicial permanece registrada.
2. `cargo fmt --check` falhou nos trechos novos; `cargo fmt` corrigiu somente formatação e a verificação posterior passou.
3. Comandos exploratórios usaram glob/nomes inexistentes (`desktop*`, `native_application.py`, `missions_api.py`, `*HANDOFF*`) e retornaram erros de caminho. Duas tentativas de edição/append partiram do diretório API usando caminhos relativos da raiz; falharam antes de editar e foram corrigidas. Um comando encadeado terminou com exit 0 apesar do erro do Python porque o `uv sync` seguinte passou; a saída foi inspecionada e o erro não foi tratado como sucesso de edição.
4. Controle nativo indisponível: erro literal de `cua.getApp` acima, sem rerun que substitua a janela por browser.
5. Audit de dependências exit 1 preservado; nenhuma atualização/fix foi aplicada.

## Processos/listeners residuais

Verificação final por `pgrep -f` limitado ao `apps/api/serve.py` e binários desktop/helpers sob `target` desta worktree: nenhum processo. Inspeção de PID/PPID/comm confirmou que a árvore de build anteriormente sob PID 55784 também terminou. Portanto nenhum listener residual é atribuível a esses processos; listeners de outras aplicações não foram encerrados. Os testes Rust/FastAPI completaram STOP/reap e limpeza UDS; os testes do runner usam portas temporárias e recolhem seus subprocessos. Não foi iniciado Vite dev server ou túnel por este sprint.

O executável nativo foi construído, mas não houve lançamento/observação verificável da janela: a ferramenta disponível não expõe seleção/controle nativo. Nenhuma afirmação de janela funcional ou IPC real decorre somente do build.

## Riscos residuais e pendências

- P2 da jornada na Tauri/WebView real continua aberto; comandos IPC/DTOs não foram observados nessa janela.
- Correção do lifecycle pronta para revisão independente, sem aceite formal.
- Garantias de sessão/grants continuam de um processo, voláteis. A revisão deste sprint cobre a superfície MAC-003 nativa e as regressões executadas; não constitui nova auditoria de toda a superfície web/Calendar.
- Warnings herdados do TestClient/HTTPX, sem mudança de dependência.
- Vulnerabilidade `source-map-js` herdada registrada pelo npm; atualização fora do escopo autorizado.
- Nenhuma autorização pendente para a correção local; smoke manual precisa de ambiente com janela nativa acessível. Fontes externas, dados reais, distribuição e deploy permanecem fora do escopo.

## Próximo gate

Reauditoria independente desta branch/commit; executar e registrar a jornada na WebView real antes de considerar fechado o segundo P2. Não fazer merge ou declarar aceite com essa evidência ainda bloqueada.
