# Erros locais de automações — 2026-10-14

## Baseline e escolha

Antes de editar, o Git confirmou `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, worktree limpa e `main` em `21f1537e14706a42e8272f92cb4f4b6dab746640`.

A fatia completa o estado de erro especificado em `LOCAL_AUTOMATIONS.md` e o diagnóstico sem conteúdo de G6-OBS-001 (`BACKLOG.md`). A API nativa já declara cinco códigos de automação, mas o parser Rust os classificava como `protocol_failure`. Por exemplo, atingir o limite de três agendamentos produzia “O backend retornou uma resposta inválida”, embora o backend tivesse respondido corretamente.

O Rust agora reconhece somente esses códigos e produz mensagens fixas em português:

| Código fechado da API | Orientação local |
|---|---|
| `automation_invalid` | Conferir horário, fuso e campos |
| `automation_not_found` | Atualizar a lista de agendamentos/execuções |
| `automation_limit` | Limite de três agendamentos; apagar um antes de cadastrar outro |
| `automation_conflict` | Estado mudou; atualizar antes de tentar novamente |
| `authorization_required` | Briefing/revisão exige consentimento das fontes e leitura ativa |

O IPC continua retornando apenas `ok` e a mensagem fixa `error`. Código desconhecido, campo extra ou ausência de código continua sendo erro de protocolo. Texto livre vindo do backend não é encaminhado. A correção não altera autorização, retry, scheduler, rotas, framing, transporte, migrations ou persistência.

## Cifra em repouso: decisão ainda pendente

Foram inspecionados `DECISIONS_PENDING.md`, `WORKFLOW_EXECUTOR.md`, `LOCAL_AUTOMATIONS.md`, `GATE2_0C_2_BACKUP_RECOVERY.md` e o contrato `g6-2/MAC_002_2_ENCRYPTED_UDS.md`. Não há desenho aprovado de chaves e compatibilidade para o SQLite ativo nesta candidata. C.2 protege o arquivo de backup com senha exclusiva e formato próprio; explicitamente não cifra o banco ativo nem define Keychain/rotação. A capability do UDS é efêmera, separada por geração/direção/finalidade e não pode ser restaurada ou reutilizada como chave de armazenamento. A passphrase G5 também não foi reutilizada.

Antes de implementar armazenamento cifrado, é necessária uma decisão sobre gestão e ciclo de vida das chaves, desbloqueio/recuperação e compatibilidade de migration/backup/restore. Conteúdo, argumentos e resultados existentes permanecem sem cifra, com uso somente sintético neste marco. Nenhum banco existente foi aberto ou convertido.

## Arquivos

- `apps/desktop/src-tauri/src/runtime_manager.rs`: tradução fechada e duas regressões no pipeline de produção de parser → classificação → JSON IPC.
- Este handoff e a referência acrescentada a `LOCAL_AUTOMATIONS.md`.

## Comandos e evidências

Todos os comandos usaram `rtk`; Cargo/uv foram executados com lockfiles e modo offline. Não houve instalação nem mudança de dependências.

| Comando e diretório | Resultado |
|---|---|
| `cargo test --locked --offline --lib local_automation_errors` em `apps/desktop/src-tauri`, antes da correção | **FAIL esperado:** 1 passou, 1 falhou. `automation_invalid` foi classificado como `protocol_failure`, reproduzindo o defeito |
| `cargo fmt --all` e `cargo fmt --all -- --check` no mesmo crate | **PASS** |
| `cargo test --locked --offline --lib local_automation` no mesmo crate | **PASS:** 4 passaram, 99 filtrados; inclui as duas regressões novas |
| `cargo test --locked --offline --lib application_protocol_encoding_and_response_parser_are_canonical` | **PASS:** 1 passou, 102 filtrados |
| `cargo test --locked --offline --lib g5_calls_are_route_closed_and_body_bounded_before_connecting` | **PASS:** 1 passou, 102 filtrados |
| `node --experimental-strip-types --test tests/runtimeCommand.test.mjs` em `apps/desktop` | **PASS:** 11 passaram |
| `uv run --locked --offline --python 3.12 pytest -q test_local_automations.py` em `apps/api` | **PASS:** 18 passaram; fixture cria SQLite novo em `tmp_path/private/memory.sqlite3` |
| `git diff --check` na raiz e checagem de whitespace do novo handoff | **PASS** |

As regressões novas usam somente campos/códigos sintéticos em memória. A regressão Python usa bancos temporários novos e relógio injetado. Não foram abertas sessões, usados segredos, conectados serviços ou iniciado o app/runner. Não foi executada suíte ampla nem build release novo; o binário release anterior não contém esta alteração até ser recompilado.

## Estado e próximo gate

Mudanças locais sem staging e sem commit, para revisão. Nenhuma alteração em `main`, outras worktrees, snapshots, migrations, lockfiles ou banco diário.

**Smoke manual: PENDENTE.** Esta rodada não abriu janela nem inspecionou interface nativa. A apresentação visual dos erros, persistência após reabertura, prompt nativo G5, Aprovações e automações continuam sem aceite visual. O P2 de Aprovações não foi fechado. Próximo gate: revisar o diff; em etapa autorizada própria, recompilar e fazer smoke sintético com banco temporário confirmado.

## Correção do achado P3 — 2026-10-14

A revisão estática seguinte identificou que `automation_invalid` estava declarado no protocolo, mas não era produzido pelos validadores. Fuso inválido gerava `AutomationError("scope_invalid")`; `_automation_error` preservava esse código e o Rust apresentava “O escopo fixo de leitura foi recusado”. O teste anterior fabricava um código que o caminho real não emitia.

Foi mantida integralmente a alteração anterior e acrescentada a distinção no ponto de validação. Dados de horário, data, fuso, quiet hours, título e mensagem passam a produzir `automation_invalid`; identificação, proprietário, catálogo fechado e consentimento/escopo continuam com suas recusas anteriores. O Rust também distingue seus prechecks de dados dos prechecks de identificador/catálogo. Não houve remapeamento global de `scope_invalid`, mudança em autenticação, autorização ou allowlists.

O teste de contrato agora usa duas fixtures compartilhadas com Rust: `apps/api/fixtures/automation_validation_error.txt` e `scope_invalid_error.txt`. Os testes da API comparam a resposta real da rota cifrada contra a primeira fixture para sete entradas inválidas e para mudança de fuso inválida. Comparam a segunda fixture contra ID de automação inválido e domínio recusado em `mission:read`. Também verificam ausência de gravação nos cadastros recusados e preservação do fuso/próxima execução após a alteração recusada. O Rust abre os mesmos bytes e verifica a mensagem IPC correspondente; os prechecks são testados sem iniciar runtime ou sessão.

Arquivos acrescentados ao escopo anterior: `apps/api/local_automations.py`, `apps/api/test_native_app_api.py` e as duas fixtures. `runtime_manager.rs` e este handoff receberam adições; `LOCAL_AUTOMATIONS.md` mantém sua alteração preexistente intacta.

Comandos desta correção, todos prefixados por `rtk`:

- `uv run --locked --offline --python 3.12 pytest -q test_native_app_api.py -k 'automation_validation_error_matches or automation_timezone_validation_preserves'` — **FAIL esperado antes da correção:** 8 falhas, demonstrando `scope_invalid` em vez do código de validação. Nenhuma falha foi ocultada.
- `uv run --locked --offline --python 3.12 pytest -q test_native_app_api.py test_local_automations.py` — **PASS:** 54 testes, 1 aviso de depreciação Starlette/httpx.
- `cargo test --locked --offline --lib local_automation` — **PASS:** 6 testes, 99 filtrados; inclui contrato API/Rust e prechecks com escopo preservado.
- `cargo test --locked --offline --lib application_protocol_encoding_and_response_parser_are_canonical` — **PASS:** 1 teste, 104 filtrados.
- `cargo test --locked --offline --lib g5_calls_are_route_closed_and_body_bounded_before_connecting` — **PASS:** 1 teste, 104 filtrados.
- `cargo fmt --all` e `cargo fmt --all -- --check` — **PASS**.

A API foi exercitada por TestClient ASGI em memória, com autenticação inteiramente sintética e SQLite novo da fixture `tmp_path/private/memory.sqlite3`; nenhum listener TCP, processo do app ou runner oficial foi iniciado. Os testes Rust não abriram janela. Banco diário, migrations, dependências e integrações externas permanecem fora da alteração. Sem commit, staging ou limpeza. **Smoke visual e P2 de Aprovações continuam pendentes.**

## Verificação final do P3 original e release — 2026-10-14

**P3 original: FECHADO no contrato de código e testes automatizados.** `Not/AZone` em criação ou mudança de fuso passa por `_zone` em `local_automations.py`, que produz `automation_invalid`. A rota da API mantém esse código pela função `_automation_error`; sua resposta real é comparada byte a byte com `automation_validation_error.txt`. O teste Rust lê essa mesma fixture, percorre o parser/classificador de produção e agora compara a mensagem IPC completa por igualdade:

> O agendamento local foi recusado. Confira horário, fuso e campos informados.

O caso de fuso inválido não recebe “O escopo fixo de leitura foi recusado”. Essa mensagem continua reservada aos casos que produzem `scope_invalid`: o teste de API confirma ID inválido e domínio recusado, e o Rust verifica a tradução exata da fixture correspondente. Códigos desconhecidos, campos extras e ausência de código continuam rejeitados pelo teste dedicado.

Inspeção estática do consumidor: `parseG5CommandResult` mantém `error`; `createAutomation` e `changeAutomationTimezone` em `App.tsx` atribuem essa mensagem a `automationError`, renderizado em `role="alert"`. Isso confirma o caminho do texto no código, sem afirmar observação da janela. Nenhuma correção adicional de produção foi necessária nesta revalidação; somente a asserção de mensagem completa foi fortalecida, preservando as mudanças locais anteriores.

Verificações focadas desta rodada, com prefixo `rtk`:

- Em `apps/api`: `uv run --locked --offline --python 3.12 pytest -q 'test_native_app_api.py::test_native_automation_validation_error_matches_rust_contract[invalid_fields0]' test_native_app_api.py::test_native_automation_timezone_validation_preserves_scope_and_stored_schedule` — **PASS: 2 testes**, 1 aviso de depreciação Starlette/httpx; bancos novos de `tmp_path` e autenticação sintética.
- Em `apps/desktop/src-tauri`: `cargo fmt --all -- --check` e `cargo test --locked --offline --lib local_automation_errors` — **PASS: 3 testes**, 102 filtrados.
- Em `apps/desktop`: `env CARGO_NET_OFFLINE=true npm run tauri -- build --no-bundle` — **PASS**, incluindo `tsc`/Vite e perfil Rust release otimizado; compilação Rust reportou 2m04s. É o comando de build já documentado, com Cargo offline.
- `git diff --check` — **PASS**.

Artefato recompilado, sem execução: `/Users/vic/.codex/worktrees/jarvis-integration-candidate/Jarvis-Victor-OS/apps/desktop/src-tauri/target/release/desktop`.

SHA-256 do arquivo: `46a9a2a409f4cb70081d9c8e1b6e946b258240177b2be6f45fb679d72392a2e0`. O build inclui as alterações locais não commitadas sobre o HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`; não é um build do checkout limpo desse SHA. `main` permanece em `21f1537e14706a42e8272f92cb4f4b6dab746640`.

Este registro atualiza a situação histórica do binário anteriormente descrito como não recompilado. Nenhum banco diário foi usado, nenhum binário foi aberto e não houve staging, commit, limpeza ou integração. **Smoke visual e P2 de Aprovações permanecem PENDENTES.** O fechamento do P3 original não constitui aceite visual ou de release distribuível.
