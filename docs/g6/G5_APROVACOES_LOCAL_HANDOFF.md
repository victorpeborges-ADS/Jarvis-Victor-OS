# Handoff — Aprovações locais G5

> As seções iniciais registram a origem do diff não commitado. A seção “Candidata local de composição” abaixo descreve e valida o estado desta worktree, que inclui o rascunho sintético e o detalhe integral.

## Baseline e objetivo

- Base: `feat/jarvis-uso-diario-mac` em `3d3444dde9d25ab67426f1c5575063dc5652caed`.
- Implementação isolada: `feat/jarvis-g5-aprovacoes-desktop`.
- Objetivo: permitir consultar e aprovar uma revisão G5 local, sintética e pendente pela aplicação desktop.

## Comportamento entregue

O desktop pede `mission:review` após consentimento explícito. Para cada item pendente, a pessoa pode buscar o snapshot completo ligado ao ID, revisão e SHA-256 que vieram da fila. O backend aceita detalhe apenas para revisão pendente em `dom_synthetic_a`, com grant ativo, snapshot íntegro e conteúdo não retido. O limite de resposta MAC-003 é aplicado ao corpo inteiro: se não couber, o backend responde com erro genérico e não trunca o texto.

A UI exibe o artefato em um bloco de texto React, identifica revisão e SHA-256, avisa que o conteúdo é dado não confiável e exige uma confirmação separada por item. O Rust chama apenas as rotas fixas de detalhe e aprovação. O backend G5 valida sessão/CSRF, grant, revisão e hash esperados; a chave idempotente estável torna uma repetição da mesma decisão segura. A aprovação altera somente o estado local da revisão.

O formato MAC-003 permanece na versão 3. Gmail, Calendar e outras ações externas seguem desconectados. A fila começa vazia. Após o grant de revisão, uma confirmação separada permite criar no máximo um rascunho sintético local; a pessoa então confere o conteúdo integral e confirma a aprovação daquela revisão/hash. Nenhuma ação externa é executada.

## Arquivos alterados

- apps/api/native_app_api.py e apps/api/native_runtime.py: rotas fixas de rascunho, detalhe e aprovação, validação do snapshot e allowlist UDS; os campos são exatos por rota.
- Testes da API e do processo: consentimento, criação sintética idempotente, detalhe vinculado ao snapshot, aprovação, limite de resposta e conteúdo em quarentena.
- apps/desktop/src-tauri: comandos G5 tipados e rotas fechadas; integração do supervisor percorre UDS de produção.
- apps/desktop/src/runtimeCommand.ts, apps/desktop/src/App.tsx, apps/desktop/src/App.css e testes IPC: criação sintética confirmada, leitura integral não confiável e aprovação por versão.
- docs/g6/USO_LOCAL_DIARIO.md: fluxo local de Aprovações documentado.

O diff de Aprovações não alterou dependências, lockfiles, migrações, esquema SQLite, grants automáticos ou controles G5 existentes. A cadeia de uso diário reaplicada na candidata já contém a migração 0016 de capturas.

## Validação reportada pela worktree de origem

Resultados finais executados nesta worktree:

- `uv run --locked pytest -q test_native_app_api.py`: aprovado; inclui acesso sem grant, detalhe vinculado ao snapshot, rejeição de conteúdo grande/quarentenado e decisão idempotente.
- `uv run --locked pytest -q test_native_runtime_process.py`: 3 aprovados.
- `cargo test --lib application_protocol_encoding_and_response_parser_are_canonical -- --nocapture`: 1 aprovado; parser aceita `sha256` e rejeita nomes iniciados por dígito.
- `cargo test --features mac003-production-supervisor-test --test mac003_production_supervisor -- --nocapture`: aprovado; launcher real, fluxo UDS de detalhe/aprovação, recusa de acesso direto às rotas, STOP, EOF, crash e restart.
- `node --test tests/runtimeCommand.test.mjs`: 6 aprovados.
- `npm run build`: TypeScript e Vite aprovados após `npm ci --ignore-scripts --offline`, usando apenas dependências já fixadas no lockfile.
- `cargo fmt --all` foi aplicado; a verificação `--check` e `git diff --check` devem ser repetidas no estado final antes da revisão.

Falhas intermediárias corrigidas durante esta execução: a fixture inicial tentou semear `/real` no app de teste UDS-only; foi separada para usar um `create_app` sintético sobre o mesmo SQLite temporário. O primeiro ensaio de aprovação também encontrou que o parser Python e o parser Rust recusavam nomes de campo com dígitos (`expected_revision`, `expected_sha256`/`sha256`); a gramática foi corrigida sem ampliar as allowlists de rota/campos. O seed da integração Rust precisou receber a passphrase sintética no ambiente isolado do subprocesso. Nenhuma falha permanece nos testes finais acima.

## Limites e próximo passo

Não foi feito smoke manual da janela Tauri/WebView nesta tarefa. Os testes validam API, IPC tipado, build e integração com o supervisor de produção, não observação da UI real. A distribuição continua fora de escopo e bloqueada pelas limitações já registradas em `USO_LOCAL_DIARIO.md`; P3 anteriores, como processo same-UID e dependência transitiva de build, não foram removidos por esta mudança.

Não houve merge, push, tag ou deploy. A worktree permanece isolada e pronta para revisão.

## Candidata local de composição — 2026-10-12

- Branch candidata: feat/jarvis-g5-aprovacoes-composed.
- HEAD: da68ac00ed868e890b5795a2822793a9a7a05abf.
- Base aceita: main em 21f1537e14706a42e8272f92cb4f4b6dab746640.
- A cadeia reaplicada em ordem vai até e20e5a02fe02299fae6fd2cb1b72f03cb59e8b28: banco/captura local, autorização de revisão, consentimento individual e rascunho sintético. Os commits posteriores de edição diária e planejador ficaram fora deste escopo; voz e avaliação também não foram combinadas.
- A implementação desktop originada em feat/jarvis-g5-aprovacoes-desktop foi copiada do diff não commitado e reconciliada aqui com o detalhe e aprovação por revisão/SHA. O three-way reportou conflitos nos arquivos compartilhados de API, transporte, RuntimeManager, IPC, UI e runbook; foram resolvidos somente nesta worktree. As origens não foram alteradas.
- O artefato verificável das origens sujas está em /tmp/jarvis-branch-inventory-20261012-hims2gmd; contém diffs binários, estados/HEADs, inventários dos untracked e cópias dos untracked não sensíveis. O inventário do checkout compartilhado registra os quatro nomes untracked sem copiar seus conteúdos.
- As worktrees paralelas de agenda, conectores Google, memória e workflows declaram migrações diferentes com o mesmo número 0018. Permanecem fora desta composição; uma futura integração precisa resolver o versionamento antes de combinar essas branches.

Validação executada nesta composição:

- API: uv run --locked --offline pytest -q test_native_app_api.py test_native_runtime_process.py — PASS, 24 testes, 1 aviso de depreciação do Starlette/httpx.
- IPC: node --test tests/runtimeCommand.test.mjs — PASS, 7 testes, incluindo despacho fixo do rascunho, detalhe e aprovação.
- Frontend: npm ci --ignore-scripts --offline — PASS, 27 pacotes locais, 0 vulnerabilidades reportadas; npm run build — PASS (TypeScript e Vite).
- Aplicativo nativo: npm run tauri -- build --no-bundle — PASS; binário release compilado sem bundle. O binário não foi iniciado.
- Rust transporte: cargo test --lib g5_calls_are_route_closed_and_body_bounded_before_connecting — PASS, 1 teste; 93 testes filtrados.
- Rust/FastAPI: cargo test --lib rust_manager_uses_fastapi_g5_over_authenticated_uds — PASS, 1 teste; 93 filtrados.
- Supervisor real: cargo test --features mac003-production-supervisor-test --test mac003_production_supervisor — PASS, 1 teste. Inclui detalhe/aprovação e criação de rascunho sintético pelo UDS autenticado; o probe same-UID recebe 404 nas rotas G5, inclusive draft; STOP, EOF, crash e restart limpam o socket.
- Formatação e whitespace: cargo fmt --all -- --check e git diff --cached --check/git diff --check — PASS.
- Nenhuma suíte selecionada foi ignorada; os 93 filtros acima são casos fora dos dois testes focados de biblioteca.

O build nativo Tauri compilou, mas não foi iniciado e nenhuma janela foi observada. Antes de chamar a tela pronta, o proprietário deve abrir o app com banco sintético temporário, consentir com mission:review em dom_synthetic_a, criar o rascunho único, conferir texto/revisão/SHA, aprovar explicitamente e confirmar que a fila esvaziou sem ação externa; fechar/reabrir a sessão e confirmar que a concessão não foi herdada. Registrar capturas sem passphrase, tokens ou dados de usuário. A candidata não está integrada à main.

## Hardening da confirmação local — 12/10/2026

Esta seção registra uma continuação isolada, sem reescrever o histórico acima. A main conferida é `21f1537e14706a42e8272f92cb4f4b6dab746640`. O SHA diário `3d3444dde9d25ab67426f1c5575063dc5652caed` informado inicialmente é anterior; a candidata diária limpa mais recente encontrada é `52917d5a5092174b35dd0d991043f61cfb71b0ec`, descendente da main e paralela à linha de `3d3444d`. Esta alteração parte de `52917d5` em `feat/jarvis-g5-approval-native-consent`; worktrees sujas da automação e do planejador permaneceram intactas.

O risco confirmado era que o WebView pudesse chamar `g5_review_approve` diretamente e fornecer `confirmed: true`, contornando o checkbox React. O comando agora não recebe confirmação do renderer. Ele busca o snapshot da revisão na API G5 por rota fixa, abre um diálogo nativo com título, ID, revisão, SHA-256 e conteúdo não confiável escapado para exibição, e só após a resposta afirmativa chama a operação de aprovação Rust, que usa a rota fixa `/v1/app/reviews/approve`. O diálogo não mantém o mutex de operação enquanto aguarda; a chamada de aprovação readquire-o e o servidor revalida sessão, grant, estado pendente, revisão e hash. Cancelamento retorna `approval_cancelled` e não chama a operação de aprovação. Não há efeito externo.

`tauri-plugin-dialog` foi adicionado como dependência direta para obter confirmação do sistema fora do WebView; a decisão continua persistida pelo backend G5. O diálogo é mostrado fora da thread principal via `spawn_blocking`. Não foi feito smoke manual da janela nesta implementação, nem integração, push, tag ou deploy. Os resultados dos testes desta candidata e eventuais limitações serão registrados antes da revisão.

Validação desta candidata:

- `cargo test --locked --lib native_review` — PASS, 2 testes aprovados, 94 filtrados. Cobrem vínculo do prompt ao snapshot não confiável e cancelamento sem chamar a aprovação.
- `uv run --locked --offline pytest -q test_native_app_api.py -k review` — PASS, 5 aprovados, 18 deselected; um aviso de depreciação preexistente de Starlette/httpx.
- `cargo test --locked --features mac003-production-supervisor-test --test mac003_production_supervisor` — PASS, 1 teste de integração do supervisor/UDS de produção.
- `node --test tests/runtimeCommand.test.mjs` — PASS, 9 testes.
- `npm ci --ignore-scripts --offline` — PASS, 27 pacotes locais e 0 vulnerabilidades reportadas; `npm run build` — PASS (TypeScript e Vite). `package-lock.json` não foi alterado.
- `cargo build --release --locked --manifest-path src-tauri/Cargo.toml` — PASS, compilação Release do executável Tauri (`target/release/desktop`), 20 crates compilados em 3m12s. O binário foi compilado, não iniciado.
- `cargo fmt --all -- --check` e `git diff --check` — PASS no estado final da candidata.

Falhas intermediárias corrigidas: os primeiros testes Rust encontraram incompatibilidades de tipos na API assíncrona Tauri e no vínculo de referências de estado; o fluxo foi ajustado e os testes focados passaram. O primeiro teste de cancelamento esperava um campo JSON que o contrato de erros não expõe; foi substituído por uma mensagem genérica e fixa, sem detalhes sensíveis. A primeira resolução da dependência tentou atualizar a família Tauri; o lock foi ajustado para manter as versões já usadas pelo projeto e acrescentar somente `tauri-plugin-dialog` 2.7.3 e dependências transitivas necessárias. Quatro tentativas de `npm run tauri -- build --no-bundle` (duas com `--verbose`) não produziram saída/artefato observável; foram interrompidas sem deixar processo ativo. A compilação Release direta por Cargo acima concluiu com sucesso.

Limite de evidência: não foi aberto o binário nem observado o diálogo nativo em uma janela real. Os testes provam que o comando IPC não aceita `confirmed` e que o caminho de cancelamento não chama a aprovação, mas não verificam visualmente o sistema de diálogo nem sua interação no macOS. Smoke manual do proprietário continua necessário antes de considerar a jornada visual confirmada. Não houve chamada a Google, provider remoto ou efeito externo.
