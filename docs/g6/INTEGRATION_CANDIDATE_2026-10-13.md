# Candidata local de integração — 2026-10-13

## Baseline e escopo

- Worktree: `codex/jarvis-integration-candidate` em `/Users/vic/.codex/worktrees/jarvis-integration-candidate/Jarvis-Victor-OS`.
- Base limpa: `594e94fb54395390146cfef28b2148554e7aeb9e` (`codex/jarvis-phase5-workflow`). Seu pai é `4ee99d48d7ab5ef19837de4f14df2a5a6eac0755`; `52917d5a5092174b35dd0d991043f61cfb71b0ec` é ancestral e merge-base observado.
- Origem da correção nativa de Aprovações: `8953642e76813589dbca71ca25820c786925f85d`, preservada em sua worktree.
- Automação selecionada: `feat/jarvis-automacoes-locais-persistentes` (scheduler com alterações locais verificadas por snapshot). A variante `feat/jarvis-automacoes-locais` não foi composta.
- Snapshot verificável das fontes: `/tmp/jarvis-integration-source-snapshots-20261013-v1`; manifestos, patches e hashes foram revalidados contra as worktrees de origem antes da cópia. Nenhuma worktree de origem foi modificada.
- A candidata inclui captura diária/G5 e executor Phase 5 do baseline, correção nativa de concessão e aprovação de revisões, e somente o scheduler local escolhido. Google, provider de IA, memória pesquisável, voz, Android e avaliação de produto ficaram fora desta composição.

## Segurança e decisões

- O diálogo nativo de passphrase do G5 continua fora do React/WebView e do IPC; o comando de abertura não recebe passphrase. A janela e o prompt não foram observados nesta execução.
- A criação de `mission:review` agora exige confirmação do diálogo nativo; o IPC não aceita um booleano de confirmação. O comando Tauri obtém a confirmação diretamente do plugin nativo e chama um método interno que exige o token privado `NativeReviewGrantConfirmed`. Aprovar cada revisão continua vinculado ao detalhe corrente (ID, revisão e SHA-256), à sessão/grant e à idempotência do backend. Cancelar não executa a escrita.
- As rotas G5, workflow e automação permanecem em allowlists fechadas sobre UDS/v3. O modelo/WebView não escolhe URL, método, comando, token ou chave de idempotência.
- O scheduler só roda com o app ativo; pausas, retomadas e exclusões invalidam ocorrências pendentes, retries são limitados e ocorrências perdidas exigem recuperação explícita. A fonte incluída é a implementação mais completa entre as duas variantes dirty: mantém `superseded`, retry/deferred de ocorrência única após restart, revogação de grants no histórico e resolução de lacuna DST de 24 horas.
- `0019_workflow_tasks.sql` já pertence à base (SHA-256 `aee3105e1b2d91d7321726acd3c0ebd4ac604c2882da35415dea4cec47953012`). A candidata não contém `0018_*.sql`; `0020_local_automations.sql` é aditiva (SHA-256 `dac74937e2fd13fd416c1e34e10cbc02233dae70596ac3b40cf0a47fa817312e`) e não altera migration aplicada. Não houve mudança em lockfiles nem dependência nova.
- Limitação antes de dados pessoais: workflow e automação guardam argumentos/conteúdo/resultado no SQLite local sem cifra de conteúdo. Manter somente dados sintéticos até decisão e mitigação de armazenamento.

## Evidências automatizadas

- `uv run --locked --offline --python 3.12 pytest -q test_local_automations.py test_native_app_api.py test_workflow_executor.py test_native_runtime_process.py::test_supervised_fastapi_g5_vertical_flow_and_stop` — **52 passaram**, 1 aviso de depreciação Starlette/httpx.
- `uv run --locked --offline --python 3.12 pytest -q test_daily_capture_gate.py test_memory_store.py test_backup_recovery.py test_native_app_api.py` — **101 passaram**, 1 aviso de depreciação.
- `node --experimental-strip-types --test tests/runtimeCommand.test.mjs` — **11 passaram**.
- `cargo test --locked --offline --lib local_automation` — **2 passaram**, 99 filtrados.
- `cargo test --locked --offline --lib native_review` — **3 passaram**, 98 filtrados.
- `cargo test --locked --offline --lib g5_calls_are_route_closed_and_body_bounded_before_connecting` — **1 passou**, 100 filtrados.
- `cargo fmt --all -- --check` — passou em `apps/desktop/src-tauri`.
- Prova de migration em bancos temporários — passou para inicialização limpa e upgrade `0019 → 0020`; 18 versões aplicadas, sem `0018`, tabelas de workflow e automação vazias. Nenhum banco diário foi aberto ou alterado.
- `npm run tauri -- build --no-bundle` — **passou**, incluindo `tsc`/Vite; release local gerado em `apps/desktop/src-tauri/target/release/desktop`. O binário não foi aberto. Build não significa smoke de janela.
- `git diff --check` — passou. O SHA do commit local da candidata é informado no handoff desta revisão.

Falhas intermediárias encontradas e corrigidas: a primeira aplicação textual produziu blocos Rust intercalados e uma allowlist de transporte inválida; `native_app_api.py` também apresentou erro de sintaxe na primeira coleta. Esses arquivos foram reconstruídos a partir do HEAD limpo e receberam somente as adições selecionadas. A primeira compilação Rust expôs atributos Tauri duplicados, helpers de teste fora da importação local e o limite de corpo ausente; foram corrigidos. A primeira suíte de migração encontrou duas listas de versões esperadas obsoletas; somente as expectativas de teste foram atualizadas para incluir `0020`, sem editar SQL aplicado. Uma tentativa inicial da prova temporária importou o nome errado da classe do store e não alterou banco; foi repetida com `SQLiteMemoryStore` e passou. O primeiro `cargo fmt` executado na raiz não encontrou `Cargo.toml`; a verificação foi repetida no crate `apps/desktop/src-tauri` e passou.

## Gates manuais ainda abertos

Nenhuma janela Tauri foi aberta nesta execução. Não considerar UI, prompt nativo, Aprovações ou automações verificados visualmente, e não fechar o P2 por teste/build.

1. Inicie o binário release local com banco sintético descartável/override e sem conta Google/provider. Confira a configuração mostrada e reinício; não inspecione nem reutilize conteúdo de banco diário existente.
2. G5: abrir sessão deve exibir entrada nativa oculta; cancelar deve manter sessão fechada. Confirmar deve criar sessão sem passar o valor por React, IPC ou logs.
3. Aprovações: criar item sintético; cancelar concessão nativa e confirmar ausência de grant no estado do servidor/SQLite; conceder e observar `mission:review`; cancelar aprovação por item e confirmar ausência de mudança; confirmar a revisão exibida e validar revisão/hash/estado e replay idempotente no servidor/SQLite.
4. Automações: criar lembrete sintético, conferir timezone/próxima execução/origem/versão/histórico; pause/resume/delete; deixar vencer com app inativo para ver `missed`; recuperar só após confirmação; conferir que retries/resultado não duplicam efeitos.
5. Registrar separadamente o que foi visto na janela, nos diálogos nativos e no estado do servidor/SQLite. Voz continua desativada e não há APK Android neste escopo.

## Estado de integração

Esta worktree é uma candidata local separada. Não foi feita integração em `main`, push, tag, deploy, OAuth, chamada externa, uso de modelo ou mudança em checkout compartilhado. O estado final, SHA e hash de dependências ficam no registro de handoff da conversa e serão atualizados após o commit local.
