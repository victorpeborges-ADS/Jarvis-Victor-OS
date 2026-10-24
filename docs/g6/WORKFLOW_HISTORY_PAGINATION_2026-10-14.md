# Histórico paginado de workflows — 2026-10-14

## BASELINE / OBJETIVO

Worktree `/Users/vic/.codex/worktrees/jarvis-integration-candidate/Jarvis-Victor-OS`, branch `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`; `main` permanece em `21f1537e14706a42e8272f92cb4f4b6dab746640`. Git foi conferido antes e depois das alterações.

Objetivo único: percorrer o histórico durável além dos quatro itens, por operação explícita e compatível com consumidores anteriores. Não houve commit, staging, merge, push, tag, deploy, execução do app ou acesso a banco diário.

## PRESERVAÇÃO

Antes de editar havia modificações em `local_automations.py`, `test_native_app_api.py`, `runtime_manager.rs`, `LOCAL_AUTOMATIONS.md`; e untracked `automation_validation_error.txt`, `scope_invalid_error.txt`, `LOCAL_AUTOMATION_ERRORS_2026-10-14.md`. Foram preservados. Nenhum reset, stash, descarte ou limpeza. A correção P3 anterior não foi reaberta. Este handoff complementa o anterior sem substituí-lo. Nenhuma outra worktree/snapshot foi alterada.

## ARQUIVOS ALTERADOS NESTA FATIA

- `apps/api/workflow_executor.py`: parser de cursor e consulta keyset somente leitura, com campos imutáveis existentes.
- `apps/api/native_app_api.py`: rota fechada nova e empacotamento por orçamento de bytes, sem mudança de `/list`.
- `apps/api/native_runtime.py`: entrada exata na allowlist cifrada.
- `apps/api/test_native_app_api.py`: nove casos novos (incluindo parametrização), testes sobre resposta real v3, SQLite temporário, compatibilidade, inserção/estado/remoção e item grande.
- `apps/api/fixtures/workflow_page_v1.txt`: resposta sintética compartilhada API/Rust/TypeScript.
- `apps/desktop/src-tauri/src/{transport.rs,runtime_manager.rs,lib.rs}`: allowlist, comando IPC novo, decoder estrito e quatro regressões novas. Alterações anteriores de Rust foram preservadas; formatação aplicada.
- `apps/desktop/src/runtimeCommand.ts` e `tests/runtimeCommand.test.mjs`: contrato TypeScript dedicado e três testes novos, preservando parser antigo.
- `apps/desktop/src/App.tsx`: primeira página explícita, carregar mais, limpar cursor ao encerrar sessão e descartar respostas de gerações anteriores da listagem.
- `docs/g6/WORKFLOW_EXECUTOR.md`, `docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md` e este handoff: contrato e evidências.

## DECISÕES / CRITÉRIOS

Contrato completo no documento do executor e emenda MAC-003: `/workflows/list` e seu DTO permanecem inalterados. `/workflows/page` é operação aditiva v1 sobre envelope v3, sem fallback. `wf1|data UTC canônica|id` tem limite de 80 bytes; keyset descendente `(created_at,id)` não muda com estados. Final devolve cursor vazio. Remover a âncora não bloqueia avanço; novos itens acima do cursor ficam para outra travessia. Não é snapshot: inserções retrodatadas abaixo da fronteira podem aparecer.

Resposta textual percent-encoded até 1.792 bytes, incluindo cursor/envelope textual; reserva de 256 para frame/nonce/tag/margem garante corpo cifrado abaixo de 2.048. Teste mede o envelope real, não só JSON. Prefixo que cabe é entregue integralmente; item que não cabe sozinho produz `limit_exceeded` sem salto ou truncamento. Cursores/dados extras são recusados. Cursor não concede autorização: sessão é validada em cada página. Nenhuma execução de tarefa, grant, aprovação ou efeito externo é desencadeado pela paginação.

Sem migration/dependência nova. Uso dos índices existentes pode requerer ordenação temporária em bases grandes; desempenho de histórico volumoso não foi medido. Cifra em repouso continua decisão pendente: nenhuma chave inventada, reutilizada ou dado convertido. Garantias de UDS, PID, HMAC antes de descriptografar, partições CTR, replay, limites e separação capability/sessão/grant foram preservadas.

## COMANDOS EXECUTADOS / TESTES

Todos prefixados por `rtk`; comandos abaixo incluem a invocação efetiva. Testes Python criam SQLite novo por fixture `tmp_path/private/memory.sqlite3`, com dados e autenticação sintéticos; ASGI TestClient sem listener TCP. Rust de paginação/parsings não inicia app, runner ou janela.

| Diretório / comando | Resultado observado |
|---|---|
| raiz: `rtk git branch --show-current`, `rtk git rev-parse HEAD main`, `rtk git status --short` | baseline e mudanças locais confirmados |
| `apps/api`: `rtk env UV_OFFLINE=1 uv run --locked pytest test_native_app_api.py -k workflow` | PASS: 11 testes na primeira rodada |
| `apps/api`: `rtk env UV_OFFLINE=1 uv run --locked pytest test_workflow_executor.py test_native_app_api.py -q` | PASS final: 50 testes, 1 aviso Starlette/httpx; rodada anterior de 49 também passou |
| `apps/api`: `rtk env UV_OFFLINE=1 uv run --locked pytest test_native_app_api.py -k workflow_page -q` | PASS final: 9 testes, 36 filtrados, 1 aviso; inclui reforço posterior de prefixo seguido de item grande |
| `apps/desktop/src-tauri`: `rtk env CARGO_NET_OFFLINE=true cargo test --locked --offline --lib workflow_page` | PASS final: 4 testes, 105 filtrados |
| mesmo crate: `rtk env CARGO_NET_OFFLINE=true cargo test --locked --offline --lib g5_calls_are_route_closed_and_body_bounded_before_connecting` | PASS: 1 teste |
| mesmo crate: `rtk env CARGO_NET_OFFLINE=true cargo test --locked --offline --lib application_protocol_encoding_and_response_parser_are_canonical` | PASS: 1 teste |
| mesmo crate: `rtk env CARGO_NET_OFFLINE=true cargo test --locked --offline --lib local_automation_errors` | PASS: 3 testes da regressão existente; desconhecidos/extras continuam rejeitados |
| `apps/desktop`: `rtk env node --test tests/runtimeCommand.test.mjs` | PASS final: 14 testes |
| `apps/desktop`: `rtk env npm run build` | PASS: TypeScript + Vite; artefatos ignorados em `dist/`, sem abrir app |
| crate: `rtk env cargo fmt --all`, `rtk env cargo fmt --all -- --check`; raiz: `rtk git diff --check` | PASS |

Não houve suíte ampla de runtime/processo/E2E nem novo build release Tauri. O binário release anteriormente gerado não contém esta paginação até recompilação autorizada posterior. Build Vite não é smoke de janela.

### Falhas intermediárias registradas

- `rtk python` não encontrou interpretador; leituras repetidas via `rtk env python3`. Buscas em `apps/desktop/scripts` e `docs/g6-2` falharam por diretórios inexistentes; contrato localizado em `docs/g6/g6-3`.
- Primeiro filtro Cargo compilou mas selecionou **zero testes**, antes das regressões novas: não contado como cobertura.
- Primeiro teste de cursor Rust: 2 PASS, 1 FAIL. Parser RFC3339 existente aceitava 30 de fevereiro; validação do cursor recebeu checagem própria de calendário, sem alteração global do parser. Rodadas posteriores passaram.
- Uma rodada da API teve 48 PASS, 1 FAIL: expectativa da rota desconhecida era 400, mas o protocolo rejeita com 401. Expectativa corrigida, sem ampliar rota.
- Outra rodada da API teve 49 PASS, 1 FAIL: fixture inicialmente calculava hash só dos argumentos; contrato real inclui `tool_id`. Fixture corrigida para o hash canônico vigente; comparação real API/fixture e Rust/TypeScript passaram depois. Nenhuma falha ocultada.

## CAPTURAS / RISCOS / PRÓXIMO GATE

Sem captura de janela, inspeção de UI ou smoke manual. Nenhum OAuth, Google, provider, voz, Android, distribuição ou serviço externo. SQLite de workflow/automação continua sem cifra de conteúdo; uso sintético somente. Cliente e backend novos precisam ser usados juntos; runtime antigo recusa a operação nova. Histórico vivo e custo de ordenação em bases grandes são limites explícitos.

**Smoke visual: PENDENTE. P2 de Aprovações: PENDENTE.** Não inferir aceite visual de teste/build. Próximo gate: revisar diff e, em etapa separada, recompilar release. Depois, proprietário em banco temporário confirmado cria mais de quatro tarefas sintéticas, observa “Carregar mais tarefas”, percorre até o fim, muda estado, verifica recarga da primeira página e ausência de duplicidade. Prompt nativo G5, persistência após reabertura e cancelamento/confirmação nativa de Aprovações seguem gates anteriores. Não integrar main antes dos gates exigidos.


## Revalidação release Tauri após paginação — 2026-10-14

O registro anterior de ausência de release pertence à implementação inicial. Nesta revalidação autorizada, branch/HEAD/main foram conferidos novamente: `codex/jarvis-integration-candidate` / `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`; main `21f1537e14706a42e8272f92cb4f4b6dab746640`. O estado inicial continha exatamente 14 arquivos modificados e 5 untracked, todos preservados.

### Processo e isolamento

Antes de sobrescrever o release padrão, foi consultado `/usr/sbin/lsof -nP -F pcftn <executável padrão>`: exit 1, sem arquivo listado ou diagnóstico. A verificação complementar `/bin/ps -axo pid=,comm=` confirmou PID **46106** associado exatamente a `apps/desktop/src-tauri/target/release/desktop` desta worktree. Só nomes de executável/PID foram consultados, sem argv ou ambiente. O processo não foi encerrado/interrompido e o binário em uso não foi sobrescrito.

Foi criado um diretório temporário isolado para Cargo. Em `apps/desktop`, executou-se exatamente:

```bash
rtk env CARGO_NET_OFFLINE=true CARGO_TARGET_DIR=/private/tmp/jarvis-pagination-release-20261014-ny1mxqhn npm run tauri -- build --no-bundle
```

**PASS, exit 0.** O beforeBuildCommand `npm run build` passou (TypeScript e Vite; 19 módulos). Cargo concluiu `release [optimized]` em **4m04s**, sem erro ou falha intermediária de compilação. Não houve correção de código ou necessidade de repetir testes focados nesta rodada; os resultados anteriores permanecem registrados acima. Cargo operou offline, sem instalação ou atualização de dependências/lockfiles.

### Artefato observado

- Caminho absoluto: `/private/tmp/jarvis-pagination-release-20261014-ny1mxqhn/release/desktop`.
- SHA-256: `b329d04deafeca7701cbedc5f1050bc4a01ce0f54e29d25c27cddbfc6172c683`.
- Tamanho: **4830424 bytes**.
- Inspeção por `file`: **Mach-O 64-bit executable x86_64**.
- Executável padrão preservado: SHA-256 antes/depois `46a9a2a409f4cb70081d9c8e1b6e946b258240177b2be6f45fb679d72392a2e0`.

Após o build, SHA-256 dos 19 arquivos dirty/untracked foi comparado ao inventário anterior: nenhum arquivo mudou, apareceu ou desapareceu. A única edição desta rodada é esta seção acrescentada ao handoff; todo o conteúdo anterior foi preservado. Artefatos de build ignorados em `apps/desktop/dist` foram regenerados pelo comando documentado. Verificação final: `rtk git diff --check` e whitespace do handoff **PASS**; branch, HEAD, main e lista de 14 modificados/5 untracked mantidos.

O diretório temporário e seu artefato foram mantidos para revisão; nenhuma limpeza foi feita. O release padrão ainda é o binário anterior: o novo artefato precisa ser selecionado explicitamente em uma futura etapa manual autorizada. Este executável foi compilado do código local não commitado, não é pacote distribuível/assinado/notarizado nem prova empacotamento do runner.

**Smoke visual: PENDENTE. P2 de Aprovações: PENDENTE.** O novo binário não foi aberto; nenhuma interface foi inspecionada ou controlada, nenhum banco diário foi acessado e nenhum smoke foi executado. Nenhum commit, merge, fast-forward, push, tag ou deploy. Próximo gate continua revisão e smoke sintético pelo proprietário em banco temporário confirmado, incluindo paginação, prompt nativo e Aprovações.


## Tentativa de smoke automatizado via Computer Use — 2026-10-14

**Resultado geral: BLOCKED antes de iniciar a candidata.** Verificação somente de Git, artefato e disponibilidade da ferramenta; nenhuma janela Jarvis foi observada. As evidências de build/API/Rust acima não contam como smoke visual.

### Identificação confirmada

- Branch: `codex/jarvis-integration-candidate`; HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`; main `21f1537e14706a42e8272f92cb4f4b6dab746640`.
- Estado inicial nesta rodada: **15 modificados e 5 untracked**, incluindo a proposta documental DEC-08 posterior ao build; todas as mudanças anteriores foram preservadas. Única edição da rodada: esta seção no handoff existente.
- Executável conferido: `/private/tmp/jarvis-pagination-release-20261014-ny1mxqhn/release/desktop`.
- SHA-256 observado e igual ao esperado: `b329d04deafeca7701cbedc5f1050bc4a01ce0f54e29d25c27cddbfc6172c683`.
- Banco usado: **nenhum**; não foi criado banco/diretório de dados/socket para a tentativa, nem acessado banco diário. Nenhuma passphrase foi gerada, lida ou digitada.

### Bloqueio observado e autorização necessária

A chamada real `await cua.getState()` retornou `apps: []` e superfícies de navegador. O contrato da ferramenta disponível nesta sessão declara **“Native computer APIs are disabled”**. Assim, ela não oferece API habilitada para ver/controlar a janela Tauri nem seus diálogos macOS. A presença de controle do Chrome não prova acesso ao aplicativo nativo e não substitui esse smoke. Não foram acessadas abas nem copiados seus conteúdos para este handoff.

Para prosseguir automaticamente, é necessário disponibilizar/habilitar **Computer Use para aplicativos nativos do macOS nesta sessão**, com acesso autorizado à janela e aos diálogos do Jarvis. Não foi observada uma recusa específica de Acessibilidade, Gravação de Tela ou autorização individual do app; portanto, não se afirma qual permissão do macOS estaria faltando. Se a ferramenta nativa posteriormente reportar essa falta, a autorização correspondente deverá ser concedida pelo proprietário. Nenhuma configuração, permissão ou plugin foi instalado/alterado nesta rodada. Não se pede execução manual dos fluxos.

O launcher documentado `scripts/run-local-desktop.sh` foi lido, mas **não executado**: aponta para o release padrão da worktree, não para este artefato temporário, e sem override escolhe o banco diário. O código/documento mostram override `JARVIS_DATABASE_PATH` e socket por geração; isso é evidência estática, não prova de isolamento de uma instância iniciada. Isolamento completo de banco/dados/socket permanece **NOT TESTED**. Não foram impressos ambientes/argv de processos nem valores de credenciais. A instância existente, incluindo PID 46106, não recebeu interação, sinal ou comando de encerramento.

### Matriz desta tentativa

| Verificação/fluxo | Estado | Evidência observada |
|---|---|---|
| Branch, HEAD, main e arquivos locais | PASS | Comandos Git read-only; estado acima |
| Identidade do binário candidato | PASS | SHA-256 do arquivo coincide com o esperado; binário não executado |
| Computer Use ver/controlar Jarvis | BLOCKED | APIs nativas desativadas; inventário não fornece apps nativos |
| Isolamento efetivo de banco/dados/socket | NOT TESTED | Nenhuma instância temporária iniciada; nenhum banco selecionado/usado |
| Runtime Pronto, UDS Autenticado, protocolo 3 | BLOCKED | Sem acesso à janela e sem iniciar candidata; não inferido do build |
| Gmail/Calendar desconectados na tela | BLOCKED | Tela não observada |
| Sessão Missões e passphrase sintética no diálogo nativo | BLOCKED | Diálogo nativo inacessível pela ferramenta disponível |
| Ideia sintética e persistência após fechar/reabrir | BLOCKED | Nenhuma captura/reabertura realizada |
| Aprovações: revisão sintética, cancelar, aprovar, hash/estado, replay | BLOCKED | Nenhuma revisão, confirmação ou decisão executada; P2 continua pendente |
| Automações: criar, fuso/próxima execução, histórico, pause/resume/delete | BLOCKED | Nenhum controle ou execução observado |
| Parar candidata e verificar processo/socket | NOT TESTED | Candidata temporária não chegou a ser iniciada |
| Screenshots da janela/diálogos | NOT TESTED | Nenhuma captura disponível; não há evidência visual a anexar |

Comandos desta rodada: Git read-only, hash via `hashlib`, leitura do launcher e busca estática de configuração; `cua.getState()`; `rtk git diff --check` e whitespace do handoff **PASS**. Nenhum teste automatizado de produto foi reexecutado para substituir o visual. Sem alteração de código/migrations/dependências, commit, merge, push, tag, deploy ou limpeza. **Smoke visual e P2 de Aprovações permanecem PENDENTES.** Próximo gate: disponibilizar Computer Use nativo e retomar a automação com isolamento confirmado antes de qualquer escrita.


### Segunda tentativa de smoke automatizado — 2026-10-14

O pedido foi repetido e a disponibilidade foi **reconsultada**, sem reutilizar o resultado anterior como se fosse observação nova. `cua.getState()` retornou novamente `apps: []` e três superfícies de navegador; as APIs nativas continuam desativadas no contrato da ferramenta. Portanto, **BLOCKED no passo 2**, antes de iniciar o executável ou criar dados. Não há evidência de qual permissão específica do macOS estaria faltando: o requisito observado é disponibilizar Computer Use nativo nesta sessão, com controle autorizado da janela e dos diálogos do Jarvis. Nenhuma configuração ou permissão foi alterada; não foi solicitado smoke manual ao proprietário.

Git reconfirmado: `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, main `21f1537e14706a42e8272f92cb4f4b6dab746640`; 15 modificados/5 untracked preservados. O arquivo `/private/tmp/jarvis-pagination-release-20261014-ny1mxqhn/release/desktop` continua com SHA-256 `b329d04deafeca7701cbedc5f1050bc4a01ce0f54e29d25c27cddbfc6172c683`, igual ao esperado.

| Fluxo nesta repetição | Estado | Evidência |
|---|---|---|
| Identidade do artefato e Git | PASS | Hash e comandos read-only executados novamente |
| Acesso visual/controlável ao Jarvis | BLOCKED | Nova consulta da ferramenta; ausência de superfície nativa |
| Pronto/UDS/protocolo/conectores, sessão nativa, captura/restart, Aprovações/replay e Automações | BLOCKED | Sem controle nativo; nenhum desses fluxos foi iniciado ou observado |
| Isolamento efetivo, banco utilizado, screenshots e parada da candidata | NOT TESTED | Nenhuma candidata temporária iniciada, nenhum banco usado, nenhuma captura disponível |

A matriz detalhada da primeira tentativa permanece com os mesmos estados. Não houve interação/sinal/encerramento do PID 46106, leitura de ambiente de processo, acesso ao banco diário, geração/digitação de passphrase ou alteração de código. Somente esta nota foi acrescentada ao handoff; `rtk git diff --check`: **PASS**. **Smoke visual e P2 de Aprovações continuam PENDENTES.**

## Revisão integrada do diff local — 2026-10-16

### Baseline, objetivo e preservação

Conferidos antes da revisão: branch `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, `main` `21f1537e14706a42e8272f92cb4f4b6dab746640`; **15 modificados e 5 untracked**, conforme o último handoff. Leitura do diff completo contra HEAD, dos três fixtures novos e dos dois handoffs novos, além dos contratos e caminhos de produção relacionados. Todos os arquivos anteriores foram preservados. Sem reset, stash, limpeza, staging ou commit.

Objetivo: revisar a integração da paginação/erros e corrigir somente defeitos reproduzidos. Nesta rodada foram editados apenas `apps/desktop/src/App.tsx`, este handoff e o teste novo `apps/desktop/tests/workflowHistory.test.mjs`. Nenhum ajuste de backend, Rust, migrations ou dependências foi necessário.

### Achados confirmados e correções

- **P2 — Invalidação incompleta das respostas do histórico (`App.tsx`, efeito inicial, `refreshWorkflowTasks`, `loadWorkflowPage` e fechamento de sessão).** As verificações de geração cobriam o sucesso, mas uma rejeição da carga inicial antiga podia apagar uma lista mais nova, e uma rejeição de refresh antigo escapava ao chamador e exibia erro em outra geração. Uma página pendente mantinha o `g5Busy` compartilhado ao mudar de seção; sua finalização também podia liberar o estado de outra operação. O fechamento explícito não invalidava tarefas/cursor/respostas imediatamente: dependia do próximo polling, inclusive se a consulta seguinte de status ficasse pendente. Reproduções com promises controladas exercitaram esses caminhos do componente real, incluindo resposta de sucesso antiga depois de fechar a sessão.
  - Correção: conferir geração também nos caminhos de erro/finalização; invalidar na limpeza do efeito e imediatamente após fechamento confirmado; limpar tarefas, cursor e detalhe juntos. O carregamento de página tem um estado próprio, combinado ao bloqueio já usado pelos controles, e uma geração antiga não pode finalizar o carregamento novo. Reiniciar a listagem cancela apenas esse estado de paginação, sem liberar uma operação G5 em andamento.
- **P3 — Microcopy contraditória (`App.tsx`, painel de workflows).** A interface ainda afirmava “sem paginação nesta versão” ao lado da operação nova. O texto agora orienta o uso de “Carregar mais tarefas” e preserva o orçamento MAC-003.

Não foram confirmados P0/P1 nem outros defeitos de produção no diff revisado. Estes achados ficam corrigidos no código local e nos testes; não constituem aceite visual.

### Conferência dos contratos e das afirmações anteriores

- **Protocolo/compatibilidade:** `/v1/app/workflows/page` é operação exata adicional nas allowlists Python/Rust, registrada no IPC Tauri. Usa o envelope v3 e campos ordenados fechados; `/workflows/list`, seu DTO e sua ordenação antiga permanecem intactos. Não há fallback para o contrato antigo. Testes da API, decoder Rust e TypeScript usam o fixture compartilhado.
- **Keyset:** consulta parametrizada por `(created_at, id)` descendentes, sem dependência de a linha âncora continuar existindo. As mudanças de estado não escrevem `created_at`. Os testes verificam empates, inserção mais nova, alteração de estado e remoção da âncora/de item ainda não visto. A leitura continua sendo de histórico vivo, com o limite já documentado para inserções retrodatadas; não é snapshot.
- **Orçamento completo:** o empacotamento mede os bytes ASCII após percent-encoding, incluindo campos/cursor. O teto de 1.792 deixa o envelope com no máximo **1.847 bytes** (corpo + frame de 7 + nonce de 16 + tag de 32), abaixo dos 2.048. O teste `_workflow_page` mede a resposta cifrada real. Prefixos são entregues inteiros e item grande recebe `limit_exceeded`; não há salto nem truncamento. Limites globais não foram ampliados.
- **Validação/autorização:** parser de cursor canônico e decoders fechados; a rota autentica a sessão e a reconfirma sob o lock a cada página. Cursor não concede acesso. Capability de transporte, sessão e grants continuam separados. PID do peer antes do envio, HMAC antes de CTR, partições por direção/sequence e proteção de replay foram inspecionados sem alteração desses caminhos; os testes focados abaixo mantiveram as recusas esperadas. Não foi reexecutada toda a suíte de supervisor/processos.
- **Automações:** `Not/AZone` percorre o validador real e retorna `automation_invalid`; ID/domínio recusados mantêm `scope_invalid`. Fixtures API/Rust, mensagens fixas, desconhecidos e campos extras passaram nos testes desta rodada. Não foi feito remapeamento global de erro nem alteração de escopo.
- **Handoffs/build:** a afirmação anterior de descarte de respostas antigas era ampla demais para os caminhos de erro e fechamento explícito; agora há regressões específicas. Os builds/hashes anteriores são evidências históricas e **não incluem as correções deste adendo**. Nenhum release foi recompilado ou executado nesta revisão. Teste de handlers/JSX em memória e typecheck não substituem observação da janela.

### Testes executados nesta revisão

Todos os comandos abaixo foram prefixados por `rtk`. Python usou bancos novos das fixtures `tmp_path`, ASGI TestClient e autenticação sintética. O default de banco foi apontado por guarda para `/tmp/jarvis-review-unused-default-20261016/memory.sqlite3`; nenhuma rotina desta suíte seleciona esse default para persistência. Node executou o componente transpilado em memória com hooks/IPC controlados, sem React DOM, GUI ou timers reais. Os filtros Cargo não iniciam o app/runner.

| Diretório / comando | Resultado nesta rodada |
|---|---|
| `apps/desktop`: `rtk node --test tests/workflowHistory.test.mjs`, antes da correção de produção | **FAIL esperado: 5 falhas**, reproduzindo descarte incompleto, bloqueio antigo, fechamento e texto contraditório |
| mesmo diretório: `rtk node --test tests/runtimeCommand.test.mjs tests/workflowHistory.test.mjs` | **PASS: 19 testes** (14 existentes + 5 novos) |
| mesmo diretório: `rtk env npm exec -- tsc --noEmit` | **PASS** |
| `apps/api`: `rtk env UV_OFFLINE=1 JARVIS_DATABASE_PATH=/tmp/jarvis-review-unused-default-20261016/memory.sqlite3 uv run --locked --offline --python 3.12 pytest -q test_native_app_api.py test_workflow_executor.py test_local_automations.py` | **PASS: 68 testes**, 1 aviso Starlette/httpx |
| crate: `rtk env CARGO_NET_OFFLINE=true cargo test --locked --offline --lib workflow_page` | **PASS: 4 testes** |
| mesmo crate, comando Cargo anterior com filtro `local_automation` | **PASS: 6 testes** |
| mesmo crate, filtros `application_protocol_encoding_and_response_parser_are_canonical`, `g5_calls_are_route_closed_and_body_bounded_before_connecting`, `ctr_partition_bounds_sequence_wrap_and_real_block_progression`, `encrypted_response_tampering_and_generation_replay_are_rejected`, `hmac_matches_known_sha256_vector` (uma execução por filtro) | **PASS: 1 teste por filtro**, 5 no total |

Falhas auxiliares não contadas como evidência do produto: a primeira versão do harness tinha recursão indevida na visitação de filhos JSX ausentes; ela foi corrigida antes da reprodução válida das cinco falhas. Após a correção de produção, uma asserção ainda procurava o texto do botão no parágrafo explicativo novo; foi ajustada para consultar a existência do botão. A rodada final de 19 testes passou. Leituras de `apps/api/conftest.py` e `test_native_runtime.py` retornaram arquivo inexistente; as fixtures e testes pertinentes foram inspecionados em `test_native_app_api.py`.

### Estado final, riscos e próximo gate

Estado final esperado e reconferido: **15 modificados e 6 untracked**; o único arquivo novo desta revisão é o teste Node. Branch/HEAD/main mantidos, sem staging. O conjunto anterior de arquivos permanece presente. `git diff --check`, whitespace dos dois arquivos untracked tocados e `cargo fmt --all -- --check`: **PASS**.

**Smoke visual: BLOCKED/PENDENTE; P2 de Aprovações: PENDENTE; DEC-08: PROPOSTA SEM DECISÃO EXPLÍCITA.** Nenhuma tentativa de GUI, execução do app, acesso a banco diário, ativação de restore ou mudança no documento DEC-08. Não houve screenshot nem aceite visual. Desempenho em bases grandes e semântica de histórico vivo continuam limites documentados. Próximo gate: revisão das correções locais; smoke sintético de janela depende de controle nativo habilitado e isolamento confirmado em etapa própria. Este adendo não fecha Aprovações nem autoriza restore.

Checagem adicional: o caminho sintético de guarda não existe ao fim dos testes (`synthetic_default_exists=False`). As comparações `git diff --no-index --check` dos arquivos novos com `/dev/null` retornaram 1 sem diagnóstico de whitespace; uma inspeção Python explícita dos dois arquivos retornou exit 0, sem espaços/tabs finais. `git diff --check` dos rastreados também retornou exit 0.

Saída final de `rtk git status --short --branch` (sem arquivos staged):

```text
* codex/jarvis-integration-candidate
 M apps/api/local_automations.py
 M apps/api/native_app_api.py
 M apps/api/native_runtime.py
 M apps/api/test_native_app_api.py
 M apps/api/workflow_executor.py
 M apps/desktop/src-tauri/src/lib.rs
 M apps/desktop/src-tauri/src/runtime_manager.rs
 M apps/desktop/src-tauri/src/transport.rs
 M apps/desktop/src/App.tsx
 M apps/desktop/src/runtimeCommand.ts
 M apps/desktop/tests/runtimeCommand.test.mjs
 M docs/g6/DECISIONS_PENDING.md
 M docs/g6/LOCAL_AUTOMATIONS.md
 M docs/g6/WORKFLOW_EXECUTOR.md
 M docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md
?? apps/api/fixtures/automation_validation_error.txt
?? apps/api/fixtures/scope_invalid_error.txt
?? apps/api/fixtures/workflow_page_v1.txt
?? apps/desktop/tests/workflowHistory.test.mjs
?? docs/g6/LOCAL_AUTOMATION_ERRORS_2026-10-14.md
?? docs/g6/WORKFLOW_HISTORY_PAGINATION_2026-10-14.md
```

## Novo release Tauri com as correções de App.tsx — 2026-10-16

**Resultado: PASS, exit 0; binário não executado.** Antes do build foram confirmados branch `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, `main` `21f1537e14706a42e8272f92cb4f4b6dab746640` e **15 modificados / 6 untracked**. Nenhum arquivo estava staged. Foi registrado um inventário SHA-256 dos 21 arquivos locais e do executável padrão antes de compilar.

### Executável padrão e isolamento do build

`rtk /usr/sbin/lsof -nP -F pcftn <executável padrão>` retornou exit 1, sem saída/diagnóstico. Uma consulta complementar de `/bin/ps -axo pid=,comm=` não encontrou processo cujo nome de executável fosse exatamente o caminho padrão desta candidata. Foram consultados somente PID/nome de executável, sem argv ou ambiente. Isso registra a observação daquele instante; nenhum processo recebeu sinal, encerramento ou interação.

Um diretório novo e privado foi criado via `tempfile.mkdtemp` em `/private/tmp`; o target padrão não foi usado. Em `apps/desktop`, o comando efetivo foi:

```bash
rtk env CARGO_NET_OFFLINE=true CARGO_TARGET_DIR=/private/tmp/jarvis-pagination-release-20261016-p_fafso7 npm run tauri -- build --no-bundle
```

O `beforeBuildCommand` executou `npm run build`: TypeScript e Vite passaram, com 19 módulos transformados. Cargo concluiu `release [optimized]` em **3m59s**. Nenhuma falha intermediária de build foi observada. Dependências foram compiladas offline no novo target, sem alteração de manifests, migrations ou lockfiles. O frontend ignorado em `apps/desktop/dist` foi regenerado pelo comando configurado.

### Artefato conferido sem execução

| Campo | Evidência observada |
|---|---|
| Binário | `/private/tmp/jarvis-pagination-release-20261016-p_fafso7/release/desktop` |
| SHA-256 | `1da2ec696befd1f5bf5637629f82953396a0c37fbbfb27abf0967c352e006549` |
| Tamanho | **4.830.424 bytes** |
| Arquitetura (`file`) | **Mach-O 64-bit executable x86_64** |
| SHA-256 de `apps/desktop/src/App.tsx`, igual antes/depois | `05382b18fcd96977358f512eb943bfda79ac3e4e6979c74af5e692e09765c261` |
| Asset frontend gerado | `apps/desktop/dist/assets/index-Br-Idyfy.js` |
| SHA-256 do asset | `967e9cbcb16511cbc2f41a6b997f74117d0b9d2b430e390739662e6718647d0a` |

Este build usa o código local não commitado, incluindo as correções de geração/carregamento/fechamento de sessão e microcopy descritas na revisão integrada acima. Não é um build do checkout limpo do HEAD e não é bundle distribuível, assinado ou notarizado.

### Preservação e estado final

Antes de acrescentar esta seção, todos os **21 hashes** e a lista de status foram comparados ao inventário inicial: nenhum arquivo local mudou, apareceu ou desapareceu durante o build. O executável padrão `apps/desktop/src-tauri/target/release/desktop` permaneceu com SHA-256 `46a9a2a409f4cb70081d9c8e1b6e946b258240177b2be6f45fb679d72392a2e0`, **4.818.112 bytes**, mesmo device/inode. Seu conteúdo não foi sobrescrito. Os registros `build-baseline.json` e `build-verification.json` foram mantidos no target temporário junto ao artefato; nenhuma limpeza foi executada.

A única edição desta rodada no conjunto local é este adendo ao handoff, preservando integralmente seus bytes anteriores. Git final continua **15 modificados / 6 untracked**, com os mesmos caminhos da saída registrada na revisão integrada acima, branch/HEAD/main inalterados e nada staged. Verificação final de preservação e whitespace: **PASS**. Sem reset, stash, staging, commit, merge, push, tag ou deploy.

Não foram repetidas suítes de testes nesta rodada: a validação executada foi o build TypeScript/Vite + Rust release e a inspeção estática do arquivo gerado. Nenhum binário/interface foi aberto, nenhum banco foi selecionado/acessado, nenhuma rotina de restore foi executada e não houve captura visual. **Smoke visual: BLOCKED/PENDENTE; P2 de Aprovações: PENDENTE; DEC-08: SEM DECISÃO EXPLÍCITA.** Próximo gate continua smoke sintético em etapa própria, com controle nativo habilitado e isolamento confirmado; este build não altera esses aceites.

## Atualização de estado — restore DEC-08 / DEC-08-A — 16/10/2026

O estado "DEC-08 sem decisão" das rodadas anteriores acima é histórico. O proprietário aprovou ativação offline de backups com schema exatamente compatível e depois aprovou DEC-08-A opção 1: **somente bancos criados sob o protocolo de leases; bancos preexistentes bloqueados para ativação** até procedimento separado e seguro confirmado pelo proprietário. Não se autorizaram upgrades, backups antigos, adoção implícita ou execução no banco diário.

A implementação Python de leases, ativação/recuperação e CLI interativo está descrita, com evidências e limites, no [handoff de restore](RESTORE_ACTIVATION_2026-10-16.md#retomada--dec-08-a-aprovado-e-implementação--16102026). Os arquivos de paginação/transportes/frontend desta candidata foram preservados; só o harness de teste nativo foi ajustado para semear dados no store já vivo, sem iniciar segundo runtime escritor. Não foi gerado novo build: esta rodada não altera Rust/frontend, e o binário release anteriormente registrado não comprova inclusão/empacotamento da implementação Python de restore.

Os testes desta retomada usam apenas bancos temporários sintéticos; não houve ativação no banco diário, abertura de interface ou execução do binário Tauri. O aceite da paginação/integração visual não foi ampliado. **Smoke visual: BLOCKED/PENDENTE; P2 de Aprovações: PENDENTE. DEC-08: escopo limitado aprovado e implementado, sujeito à revisão técnica; admissão legada e política ampla de atualização continuam fora do escopo.**
