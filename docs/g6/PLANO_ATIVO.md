# Plano ativo

O plano de execução das dez frentes está só na cópia de trabalho

`/Users/vic/Freela/Jarvis-Victor-OS/docs/ROADMAP_INTEGRADO_2026-10-17.md`

junto com o `AGENTS.md` modificado dessa mesma cópia. A seção 13 mantém as dez frentes sequenciais; a seção 14 contém o estado reconciliado em 18/10/2026. A leitura consolidada de 23/10/2026, com as divergências preservadas, está em `docs/g6/PROJECT_READINESS_2026-10-23.md`. Este checkout não duplica o roadmap.

O `AGENTS.md` desta candidata continua sendo o contrato de código dela, inclusive o aceite local do Gate 2.0-E e o limite de escrita externa. Não copiar o plano para cá: as duas redações divergiriam.

O manifesto de build gerado por `apps/api/export_build_manifest.py` descreve esta worktree. Ele não substitui `GET /v1/version`.

## Evidência da frente de memória local — 22/10/2026

Na candidata `codex/jarvis-integration-candidate`, a memória local lista categorias/domínios, exibe proveniência/revisão e permite CRUD com sessão/CSRF e exportação explícita pelo seletor nativo. A exclusão grava tombstone com a purga; backup novo reaplica tombstones antes de liberar restore cifrado, e backup legado exige confirmação de risco. Baseline anterior à rodada de estabilização: o grupo focado passou com 141 testes, mas a suíte API completa falhou (263 failed, 293 passed, 178 errors), incluindo fixtures sem chave e o caminho antigo `restore_activation` que tratava SQLite claro como único formato. O resultado final está registrado abaixo. Limites estão no ADR-012. Smoke visual não executado.

## Evidência da frente de conversa local — 22/10/2026

A conversa passa da UI pelo IPC tipado, Runtime Manager/UDS e FastAPI ao gateway e à leitura fundamentada; as ferramentas e a validação de sessão/domínio são decididas no servidor. Fontes são exibidas com ID/tipo/domínio, texto citado permanece literal e base insuficiente retorna sem resposta. DEC-14 persiste no snapshot cifrado apenas ID aleatório e metadados mínimos, expira após 24 h de inatividade e não recupera sessão/grants após reabertura; turnos, prompts, respostas e fontes não persistem. Artefatos validam origem/versão/hash e usam fragmentos sem elevar o teto de 2.048 bytes. Baseline anterior à estabilização: `test_front2_continuity.py` passou (4), grupo focado passou (141) e a API completa falhou (263 failed, 293 passed, 178 errors). Rust passou com 112 unitários + 1 integração e 9 ignorados; formatter passou após 50 hunks de estilo em `runtime_manager.rs` (43) e `transport.rs` (7). TypeScript IPC: 26 passed; `tsc --noEmit` e build passaram. Keychain real, provider real e smoke visual permanecem não testados.

## Evidência da estabilização da suíte da API — 22/10/2026

Após a reprodução e correção dos grupos de chave ausente, SQLite legado/ciphertext em `restore_activation`, setup/migração de fixtures e 503 em APIs dependentes do store, os grupos focados de cifra, memória, tombstones, restore/ativação e continuidade passaram (246 testes); as regressões afetadas finais passaram (34 testes). Na candidata, em `apps/api`, `uv run --locked --offline --python 3.12 pytest -q --tb=short` terminou com 735 passed, 2 warnings de depreciação Starlette e exit 0. `restore_activation` recusa snapshots selados sem abrir ciphertext ou staging em claro; o fluxo cifrado de backup/restore é exercitado separadamente. Restore legado sem tombstone continua bloqueado até confirmação explícita. Os testes verificam que o arquivo ativo é selado, sem cabeçalho/canário de SQLite claro, e que o diretório temporário de validação fica vazio. Keychain real, smoke visual, provider real, OAuth, efeitos externos, APK/aparelho e assinatura/notarização continuam NOT TESTED ou fora desta rodada; aprovação da suíte API não é aceite de uso ou distribuição.

## Revalidação das pendências Keychain/Web/mobile — 22/10/2026

Evidência detalhada somente na seção 16 do roadmap compartilhado indicado acima: Keychain nativo NOT TESTED por ausência de isolamento verificável, sem criação/acesso a Keychain; Web typecheck PASS, suíte completa FAIL (67 passed, 1 failed por `listen EPERM` sob bloqueio de rede), build BLOCKED por fontes Google; mobile BLOCKED por dependências indisponíveis offline. Desktop e smoke visual NOT TESTED nesta rodada. Nenhuma alteração de produto ou lockfile; sem aceite de uso ou distribuição.

## Validação Web offline resolvida — 22/10/2026

A seção 16 do roadmap compartilhado registra a evidência atual, que substitui os resultados Web anteriores: suíte completa PASS (68 testes em 16 arquivos), typecheck PASS e build PASS (11 páginas estáticas). O teste original de readiness conserva a recusa da resposta sem prova HMAC; política de teste permite somente loopback literal usado pelo teste, sem rede externa. Fontes Google removidas em favor de pilhas CSS do sistema, com possível mudança de métricas/quebras de linha; smoke visual NOT TESTED. Nenhuma dependência instalada ou lockfile alterado. Keychain nativo continua NOT TESTED; mobile continua BLOCKED; nenhuma dessas frentes foi executada nesta rodada.


### Validação desktop após Keychain descartável — 22/10/2026

Candidata validada em `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`. Validações offline: `cargo fmt --all -- --check` PASS; `CARGO_TARGET_DIR=/tmp/jarvis-rust-test-target-20261022-01a16581 CARGO_NET_OFFLINE=true cargo test --locked --offline --all-features -- --skip keychain` PASS para o restante da suíte Rust (108 unitários + 1 integração, 0 falhas, 9 ignorados, 6 filtrados). Os seis testes de Keychain descartável não foram repetidos por restrição explícita: a seção anterior documenta 6 PASS em execução anterior; isso não é execução desta rodada nem PASS da invocação sem filtro. O harness ainda usa APIs de Keychain de arquivo depreciadas no SDK macOS, inclusive `SecKeychainCreate`/`SecKeychainDelete`.

Node/IPC `node --test tests/runtimeCommand.test.mjs tests/workflowHistory.test.mjs`: PASS, 26 testes. Desktop frontend: `./node_modules/.bin/tsc --noEmit` PASS; `./node_modules/.bin/vite build --outDir /tmp/jarvis-desktop-dist-20261022-01a16581` PASS. `git diff --check`: PASS. Nenhum processo com cwd na candidata foi encontrado antes do build Tauri; alvo novo inexistente e sem arquivos abertos antes do início. Para preservar `apps/desktop/dist`, o CLI usou config temporária em `/tmp` com `beforeBuildCommand` vazio e `frontendDist` apontando para o build temporário. `CARGO_NET_OFFLINE=true CARGO_TARGET_DIR=/tmp/jarvis-tauri-target-20261022-01a16581 npm_config_offline=true ./node_modules/.bin/tauri build --no-bundle --config /tmp/jarvis-tauri-validation-override-20261022-01a16581.json`: PASS, exit 0, release em 4m05s, sem bundle. Artefato Mach-O `x86_64`: `/tmp/jarvis-tauri-target-20261022-01a16581/release/desktop`, SHA-256 `1d74be38f142040969f12384748f36ecc1da6388e8f2877b2b10934cf1c4e2a0`; não executado.

Login Keychain, Data Protection Keychain, prompts e smoke visual: NOT TESTED. Mobile: BLOCKED por dependências ausentes. Provider real, OAuth, efeitos externos, APK e assinatura permanecem fora desta validação. Nenhuma captura/demo visual foi produzida; estes resultados não declaram prontidão para uso ou distribuição.

## Reconciliação de exclusões posteriores ao backup — 22/10/2026

Rodada restrita ao restore/ativação offline da candidata `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`. União do ledger atual com o snapshot, replay antes da ativação, preservação para backups futuros e staging/rollback cifrados para destino selado. Identidades/revisões sem linhagem comprovada falham fechado; nenhum relógio vence uma exclusão. Legado sem decisões exige confirmação de possível ressurgimento. Restore isolado sem banco atual explícito continua conhecendo somente o snapshot; cópias históricas não são sanitizadas e tombstones não expiram.

Evidência: regressão completa de sete módulos PASS (234), reconciliação PASS (93), processo nativo PASS (4), sem filtros/skips; 1 aviso Starlette/TestClient. Execuções FAIL intermediárias e suas correções estão preservadas no ADR-012 e em `RESTORE_ACTIVATION_2026-10-16.md`. O roadmap compartilhado recebe apenas a evidência desta rodada, sem cópia integral aqui. Smoke visual NOT TESTED/BLOCKED; mobile BLOCKED sem nova execução; provider real, OAuth, efeitos externos, APK e assinatura fora. Sem aceite de uso/distribuição e sem nova frente de produto.

## Conversa local da interface até a API — 23/10/2026

A seção Conversa já envia a pergunta por `groundedRead` → `g5_conversation_ask` → `POST /v1/app/conversation/ask`. DEC-14 permanece: no snapshot cifrado só ficam o ID opaco e os metadados mínimos; prompt, resposta, fontes, tokens e grants continuam voláteis e somem no lock. Reabrir o ID não restaura a sessão. Fato confirmado foi citado pela rota autenticada sem promover instrução embutida. Artefato grande segue no fragmento existente, sem rota nova e sem passar de 2.048 bytes na resposta normal. Focados: 59 passed. Suíte API: 840 passed, 2 warnings, exit 0. Smoke visual NOT TESTED. Sem aceite de uso ou distribuição.

## Regressão de contrato Rust e frontend — 23/10/2026

Sem falha e sem correção. Rust com `--all-features` e `--skip keychain`, alvo novo em `/tmp`: 108 passed na lib, 9 ignored, 6 filtered, 1 integração passed. O teste de citação aceitou fato confirmado e recusou tipo desconhecido. IPC: 28 passed. Typecheck PASS. Build do Vite em `/tmp` PASS, sem tocar `apps/desktop/dist`. `cargo fmt --check` e `git diff --check` PASS. Smoke visual NOT TESTED/BLOCKED. Sem aceite de uso ou distribuição.

## Rotação da chave selada — 23/10/2026

O commit encerra o rollback. A cópia de recuperação só é finalizada depois da geração nova validada e da conta antiga ausente; apagá-la não apaga backups `.jvb`. `resume` da mesma operação não gira de novo. `begin` de outra operação só segue depois de `finalized`. API: 891 passed, 2 warnings, 436,02 s. `test_storage_key_rotation.py`: 34 passed. Lib Rust: 122 passed, 9 ignored. UDS: 1 passed, `cleanup_removed=true`. IPC: 28 passed. Typecheck PASS. Build `--no-bundle`: `/tmp/jarvis-tauri-nobundle-20261023-lifecycle/release/desktop`, SHA-256 `19a5e53ed8829e36590628004506c912e03a4d2f0c70958af3d9984abd14016f`; o binário não foi aberto. Smoke visual NOT TESTED/BLOCKED. Sem aceite de uso ou distribuição. O detalhe está no ADR-013.

## Auditoria do banco selado — 23/10/2026

Sem lacuna reproduzida e sem mudança de produção. O desbloqueio continua no comando existente, pelo UDS, com o processo nascendo bloqueado. Python: 13 passed. Rust isolado de Keychain: 6 passed. Smoke visual NOT TESTED/BLOCKED. Sem aceite de uso ou distribuição.

## Cobertura IPC de fato confirmado — 23/10/2026

O teste existente de `runtimeCommand.test.mjs` fez a ponte simulada devolver `confirmed_fact`. `groundedRead` preservou ID, tipo, domínio e citação. Recusas de ferramenta, domínio não autorizado e campos desconhecidos permaneceram. IPC: 28 passed. Typecheck PASS. Sem mudança de produção. Smoke visual NOT TESTED/BLOCKED. Sem aceite de uso ou distribuição.

## Regressão da suíte API após a reconciliação — 23/10/2026

Candidata `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`. Em `apps/api`, `uv run --locked --offline --no-env-file pytest -q --tb=short` com `JARVIS_DATABASE_PATH` novo em `/tmp`, depois descartado: **838 passed, 2 warnings, 428,37 s, exit 0**. Nenhuma falha e nenhuma correção de código. O arquivo sintético do override não foi criado. Inode, tamanho e mtime do banco diário permaneceram iguais antes e depois. `git diff --check` PASS nos dois checkouts. Smoke visual NOT TESTED. Sem aceite de uso ou distribuição. Detalhe no roadmap compartilhado.
