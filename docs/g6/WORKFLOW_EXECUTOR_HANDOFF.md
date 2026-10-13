# Handoff — executor local de workflows (Phase 5)

## BASELINE

- Repositório: `/Users/vic/Freela/Jarvis-Victor-OS`.
- `main` confirmada: `21f1537e14706a42e8272f92cb4f4b6dab746640` (igual à informada).
- Candidata diária informada `3d3444dde9d25ab67426f1c5575063dc5652caed` existe; a candidata mais recente e ancestral é `4ee99d48d7ab5ef19837de4f14df2a5a6eac0755` (12/10/2026), usada como base.
- Checkout compartilhado: `feat/gate2.0-e-integracao-web-api` em `e648e92467396ce67b75019858fbcd0ee5557042`, diferente das referências fornecidas. Nenhuma mutação foi feita nele.
- Branch isolada de revisão: `codex/jarvis-phase5-workflow`, no worktree `/Users/vic/.codex/worktrees/jarvis-phase5-workflow/Jarvis-Victor-OS`, inicialmente em `4ee99d48d7ab5ef19837de4f14df2a5a6eac0755`.
- Já existia outro worktree candidato em `feat/jarvis-workflow-executor`, com mudanças não commitadas. Seu diff foi copiado para esta branch isolada; o worktree original permaneceu intacto.
- Os quatro untracked do checkout compartilhado foram preservados: `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md`, `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md`, `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` e `package-lock.json`.

## OBJETIVO

Implementar o executor local da Phase 5 para propostas tipadas e simulações sintéticas, preservando MAC-002.2/MAC-003 e o fluxo G5. A implementação fica pronta para revisão e não integra serviços externos.

## ARQUIVOS ALTERADOS

- API e persistência: `apps/api/local_security.py`, `apps/api/main.py`, `apps/api/native_app_api.py`, `apps/api/native_runtime.py`, `apps/api/migrations/0019_workflow_tasks.sql`, `apps/api/workflow_executor.py`.
- Testes da API: `apps/api/test_memory_store.py`, `apps/api/test_native_app_api.py`, `apps/api/test_native_runtime_process.py`, `apps/api/test_workflow_executor.py`.
- Cliente nativo: `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/Cargo.lock`, `apps/desktop/src-tauri/src/lib.rs`, `apps/desktop/src-tauri/src/runtime_manager.rs`, `apps/desktop/src-tauri/src/transport.rs`.
- UI e testes IPC: `apps/desktop/src/App.css`, `apps/desktop/src/App.tsx`, `apps/desktop/src/runtimeCommand.ts`, `apps/desktop/tests/runtimeCommand.test.mjs`.
- Documentação: `docs/g6/WORKFLOW_EXECUTOR.md` e este handoff.

## DECISÕES

- O catálogo executável é fechado: `draft_note` e `simulate_action`. Ferramentas externas (`send_message`, `pay`, `delete_record`, `invite_member`) permanecem desabilitadas.
- Modelo/renderer não definem URL, método HTTP, shell, comando, headers ou ferramenta arbitrária. O Rust chama apenas rotas UDS fixas; a API valida argumentos tipados com schemas fechados.
- Sessão e grant seguem separados; approvals, revalidação de sessão/grant/hash, expiração e uso único permanecem autoritativos no backend. Revogação da concessão de revisão tem rota fixa.
- Conteúdo submetido aparece como dado não confiável. A simulação usa serviço/conta/alvo sintéticos fixos e registra `sent=false` com `data_sent=[]`.
- A WebView deixou de coletar e enviar a passphrase G5. `g5_session_open` não recebe argumentos; o macOS pede a credencial em diálogo nativo oculto via `/usr/bin/osascript`, chamado sem shell e com script fixo. O segredo não fica em argv, WebView, logs, `stderr` ou texto de erro. Saída padrão é capturada em memória protegida e `SecretText` é limpo ao sair de escopo. Outras plataformas falham fechado.
- A listagem retorna até quatro tarefas para respeitar o limite de 2.048 bytes do MAC-003; paginação fica pendente. SQLite guarda argumentos/resultados em texto simples, conforme limitação documentada.
- O único novo requisito direto Rust é `serde_json`, usado para validar as respostas JSON tipadas recebidas do backend.

## COMANDOS EXECUTADOS

Resultados finais nesta worktree:

- `rtk uv run --locked pytest -q` (`apps/api`): **359 passed**, 2 avisos de depreciação Starlette/httpx, em 79,24 s.
- `rtk cargo test --lib` (`apps/desktop/src-tauri`): **89 passed, 9 ignored**.
- `rtk cargo test --features mac003-production-supervisor-test --test mac003_production_supervisor`: **1 passed**; usa FastAPI supervisionada via UDS e dados sintéticos.
- `rtk cargo fmt --all -- --check`: **pass**.
- `rtk node --test tests/runtimeCommand.test.mjs` (`apps/desktop`): **10 passed, 0 failed**.
- `rtk npm run build` (`apps/desktop`): **pass** (`tsc` + Vite).
- `rtk npm run tauri -- build --no-bundle` (`apps/desktop`): **pass**; binário produzido em `apps/desktop/src-tauri/target/release/desktop`.
- `rtk proxy git diff --check`: **pass**.
- Testes unitários verificam o delimitador da saída nativa com passphrase sintética; nenhum diálogo nativo foi aberto.

### Falhas intermediárias resolvidas

- O primeiro `rtk npm run build` falhou com `tsc: command not found`, pois a worktree não tinha `node_modules`. `rtk npm ci --ignore-scripts --offline` instalou 27 pacotes do lockfile; auditoria reportou 0 vulnerabilidades; o build posterior passou.
- Uma execução inicial da suíte API teve 357 pass e 2 falhas: expectativas de migração antigas não listavam `0019_workflow_tasks`. As expectativas foram atualizadas; a suíte final passou integralmente.
- A primeira suíte Rust teve 86 pass, 1 falha e 9 ignorados por uma asserção de teste com mensagem de cancelamento antiga. A asserção foi alinhada à mensagem fixa já emitida; Rust final passou.
- Um build após remover o estado do campo WebView apontou `setPassphrase` ainda usado na navegação. A referência residual foi removida e os builds finais passaram.
- A chamada inicial ao `rtk proxy python` não encontrou `python`; scripts subsequentes usaram `rtk proxy python3`. Um script de edição também parou ao detectar duas expectativas de migração idênticas em vez de uma; a edição foi reaplicada explicitamente às duas ocorrências.
- Uma inspeção de processo com `rtk proxy pgrep -alf 'cargo|rustc|tauri'` exibiu argumentos e variáveis de ambiente de processo não relacionado. A saída não foi copiada para arquivos nem usada; pode ter incluído um valor de ambiente com aparência de token no resultado desta sessão. Não reproduzirei esse valor. Não conectei Google nem consultei arquivos de credenciais; interrompi esse tipo de inspeção.

## TESTES PASS/FAIL/BLOCKED

- **PASS:** suíte API, suíte Rust de biblioteca, integração supervisionada MAC-003, IPC desktop, TypeScript/Vite, build Tauri release e formatação Rust.
- **FAIL final:** nenhum.
- **BLOCKED / não executado:** smoke visual/manual da janela Tauri e do diálogo macOS. O binário foi compilado, mas a janela não foi aberta; não há alegação de validação visual. E2E visual não foi executado.

## CAPTURAS/DEMOS

Nenhuma captura. Nenhuma janela foi aberta. O diálogo nativo foi coberto somente pelo parser de saída e por testes sintéticos; o comportamento visual/interativo ainda precisa de smoke manual local.

## RISCOS RESIDUAIS

- Argumentos e resultados necessários à durabilidade ficam em SQLite local não cifrado.
- Histórico persistido mostra no máximo quatro itens até existir paginação no protocolo MAC-003.
- Cancelamento impede início; cancelamento cooperativo durante uma execução longa ainda não existe.
- Prompt por AppleScript/macOS foi compilado, mas não exercitado visualmente. Falha/cancelamento é reportado por mensagem fixa; a confirmação real precisa de smoke local com segredo sintético.
- A aceitação destes testes não substitui auditoria independente de segurança nem altera o estado formal de aceite G5/G6.

## PENDÊNCIAS DE AUTORIZAÇÃO

Nenhuma autorização externa foi solicitada ou usada. Não conectei Google, não inseri credenciais, não li dados pessoais de contas, não aceitei custos e não fiz push, tag, deploy, fast-forward ou merge. Houve somente o desvio de saída de processo descrito acima. Integrações externas permanecem fora deste escopo e exigem autorização específica do proprietário.

## PRÓXIMO GATE

Revisão independente da branch e smoke manual da janela/dialogo macOS usando somente credencial sintética. Depois, registrar aceite separado antes de qualquer integração externa. Esta entrega para antes de integração, publicação ou merge.

## WORKTREE E CLEANUP

A branch local fica no worktree gerenciado acima, separada do checkout compartilhado e pronta para revisão. O worktree de origem `feat/jarvis-workflow-executor` não foi alterado; o checkout compartilhado e seus quatro untracked permanecem preservados. Não foi executado reset/clean nem removido conteúdo. Diretórios ignorados de dependências/build (`.venv`, `node_modules`, `target`, `dist`) permanecem no worktree para facilitar revisão/reprodução. Nenhum push, tag ou integração foi feito.
