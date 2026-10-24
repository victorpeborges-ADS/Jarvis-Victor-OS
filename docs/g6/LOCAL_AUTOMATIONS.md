# Automações locais — primeiro marco

**Estado:** implementação candidata na branch `feat/jarvis-automacoes-locais-persistentes`, baseada em `52917d5a5092174b35dd0d991043f61cfb71b0ec`; requer revisão e smoke manual no Tauri antes de aceite. Não representa distribuição.

**Base verificada em 2026-10-13:** `main` = `21f1537e14706a42e8272f92cb4f4b6dab746640`; candidata diária e HEAD desta worktree = `52917d5a5092174b35dd0d991043f61cfb71b0ec`. `main` é ancestral da candidata; a candidata não é ancestral de `main`. O trabalho desta fase segue não commitado e isolado.

## Escopo e execução

Os agendamentos são persistidos no SQLite local pela migração 0020_local_automations.sql. O worker é criado somente no lifespan de create_native_app, dentro do FastAPI supervisionado pelo app. Ele verifica a fila a cada 15 segundos e é cancelado no shutdown. Não instala daemon, serviço de login, cron do sistema ou servidor sempre ligado.

O primeiro marco aceita até três agendamentos ativos/pausados/concluídos, dos tipos. Nomes têm até 24 caracteres e texto de lembrete até 32 para caber no limite atual da requisição G5:

- reminder.v1: texto escrito pelo usuário; produz rascunho/lembrete local.
- morning-briefing.v1: resumo determinístico de até duas capturas e três missões locais.
- idea-mission-review.v1: revisão determinística das mesmas fontes locais.

Briefing e revisão exigem consentimento de origem no cadastro e mission:read válido no instante de execução. O workflow não conserva grant nem sessão; fechamento, expiração ou revogação bloqueiam a leitura. Nenhum tipo chama modelo, rede externa, Gmail, Calendar, ferramenta ou ação com efeito externo. A saída aparece no aviso dentro da janela e no histórico local.

## Tempo, atraso e repetição

Recorrência diária significa hora de parede no fuso IANA salvo. A próxima execução é calculada em UTC e apresentada no fuso do agendamento. Em horário ambíguo durante o fim do DST usa-se a primeira ocorrência; em horário inexistente no início do DST avança-se minuto a minuto até o primeiro horário válido, inclusive saltos históricos de data inteira. Trocar o fuso recalcula a próxima ocorrência; o horário local configurado permanece.

Se o app/runtime inicia com uma execução vencida ou interrompida, registra missed e não recupera automaticamente, inclusive para agendamento de uma vez. A tela notifica o usuário e oferece recuperação com confirmação explícita. Enquanto o app está ativo, atraso superior a dois minutos também vira missed; atraso menor pode executar. Quiet hours adiam a execução até o próximo fim da janela.

Cada ocorrência tem chave idempotente determinística e restrição única no banco. Transações BEGIN IMMEDIATE serializam a reivindicação. Erros transitórios de SQLite têm no máximo duas novas tentativas automáticas (três tentativas totais, atrasos de 15 e 30 segundos); outras falhas terminam como failed. Um retry ou adiamento por quiet hours retomado mais de dois minutos após o horário persistido vira `missed`, inclusive depois do sono do Mac, e exige recuperação confirmada. Nova tentativa manual e recuperação exigem confirmação, e workflows que leem missões revalidam o grant. A API também exige `mission:read` atual ao devolver histórico e resultado desses workflows; revogar o grant bloqueia novas leituras.

Uma execução ainda não iniciada é marcada `superseded` quando o usuário pausa, apaga ou muda o fuso do agendamento. A ocorrência fica no histórico, mas não roda com a configuração antiga. Uma execução já iniciada termina localmente; o worker não inicia outra enquanto processa a atual.

## Estado visível e limites

A tela mostra fuso, próxima execução, fontes, versão do workflow, estado, quiet hours, histórico, tentativas, falhas e o rascunho produzido. Pausar e retomar preservam a configuração. Apagar retira o agendamento da execução; os registros persistidos ficam no SQLite, mas automações removidas não aparecem mais no painel.

O primeiro marco oferece aviso dentro da janela do app; não pede permissão para notificação do macOS e não promete entrega quando o app estiver fechado. Há recorrência diária ou única, sem regras de calendário avançadas. A base continua single-user/local e depende do ciclo de vida do runtime supervisionado. Smoke visual da tela, do aviso e da recuperação permanece pendente do proprietário.

O SQLite atual mantém `message` e `result_text` em texto simples. Permissões privadas do arquivo/diretório reduzem acesso local, mas não cifram o conteúdo. Nesta fase os testes e fontes são sintéticos; dados pessoais só devem ser usados após decisão separada sobre proteção em repouso. Os workflows de briefing/revisão não persistem sessão nem grant e revalidam `mission:read` a cada execução; não há método/URL genérico, chamada de modelo ou escrita externa.

## Evidência de implementação

Os testes usam relógio injetável, banco temporário e conteúdo sintético. Cobrem DST, mudança de fuso, atraso, quiet hours, reinício, idempotência concorrente, retries limitados, pausa/retomada/remoção, migração e fluxo local de leitura. A integração de processo usa o runner FastAPI supervisionado; o caminho IPC usa allowlist de comandos e rotas fixas.

Comandos focados executados nesta candidata em 2026-10-12:

- `uv run --locked pytest -q test_local_automations.py test_native_app_api.py` — 42 passaram; 1 aviso de depreciação de `starlette.testclient`/`httpx`.
- `uv run --locked pytest -q test_native_runtime_process.py::test_supervised_fastapi_g5_vertical_flow_and_stop` — 1 passou; o runner FastAPI supervisionado encerrou no caminho normal.
- `node --test tests/runtimeCommand.test.mjs` — 10 passaram.
- `npm ci` — instalação pelo lockfile; lockfile permaneceu inalterado. O audit informou 1 advisory high severity entre 28 pacotes; nenhuma atualização foi aplicada.
- `npm run build` — `tsc` e build Vite passaram.
- `cargo fmt --all -- --check` — passou após formatar o código Rust da candidata.
- `cargo test --lib automation` — 2 passaram; 94 filtrados.
- `cargo test --lib g5_calls_are_route_closed_and_body_bounded_before_connecting` — 1 passou; 95 filtrados.
- `git diff --check` — passou.

Falhas intermediárias: a primeira tentativa do build não encontrou `tsc` porque a worktree não tinha `node_modules`; `npm ci` instalou somente as dependências fixadas, e o build seguinte passou. A primeira verificação `cargo fmt --check` encontrou diferenças de formatação nos arquivos Rust novos/alterados; `cargo fmt --all` corrigiu somente a formatação e a verificação posterior passou. A suíte Rust completa não foi executada: os testes Rust foram filtrados para parsers/limites de automação e allowlist de transporte. Não houve testes ignorados nas execuções focadas de pytest ou Node; os números “filtrados” do Cargo não são testes ignorados.

Os testes usam relógio injetado e banco temporário para DST (inclusive lacuna histórica de 24 horas), mudança de fuso, duplicidade concorrente, reboot, atraso, quiet hours, retry e recuperação explícita. A regressão de API confirma que revogar `mission:read` bloqueia novas leituras de histórico/resultado de briefings e revisões, sem bloquear lembretes locais. A integração de processo verifica o fluxo local no FastAPI supervisionado; os testes não conectam provedores, Google ou serviços externos.

O smoke visual real da janela Tauri não foi executado nesta rodada; build e testes não provam a experiência da janela. Roteiro manual: crie um lembrete sintético único para alguns minutos à frente e um briefing com consentimento explícito das fontes; confira fuso e próxima execução; pause/retome e remova um agendamento; deixe o runtime aberto até uma execução e confira aviso/histórico; encerre o app antes de outra ocorrência, reabra e confirme `missed`, recuperando-a somente após a confirmação apresentada. Registre separadamente o que foi visto na janela e o estado no histórico da API. Estes testes/builds não substituem o smoke nem constituem aceite formal.

## Revalidação e correção — 2026-10-13

A revisão encontrou uma falha no restart: um agendamento `once` com execução em `retry_wait` podia ser marcado `completed` se o app reiniciasse depois da ocorrência original, mas antes do horário do retry. `startup_reconcile` agora preserva a ocorrência enquanto `next_attempt_at_utc` ainda é futuro. A regressão também confirma que uma execução adiada por quiet hours sobrevive ao restart até o fim da janela.

Verificações executadas na worktree isolada, usando relógio injetado e bancos temporários:

- `uv run --locked --offline --python 3.12 pytest -q test_local_automations.py` — 18 passaram após a correção; inclui DST, mudança de fuso, duplicidade concorrente, reboot, atraso, quiet hours, retries, recuperação e migration.
- `uv run --locked --offline --python 3.12 pytest -q test_local_automations.py test_native_app_api.py` — 43 passaram, 1 aviso de depreciação de `starlette.testclient`/`httpx`.
- `uv run --locked --offline --python 3.12 pytest -q test_native_runtime_process.py::test_supervised_fastapi_g5_vertical_flow_and_stop` — 1 passou.
- `node --test tests/runtimeCommand.test.mjs` — 10 passaram.
- `npm run build` — TypeScript e Vite passaram.
- `npm run tauri -- build --no-bundle` — passou; perfil release, binário local gerado em `apps/desktop/src-tauri/target/release/desktop` (compilação Rust reportou 4m23s). O binário não foi aberto.
- `cargo test --locked --offline --manifest-path src-tauri/Cargo.toml --lib automation` — 2 passaram, 94 filtrados.
- `cargo test --locked --offline --manifest-path src-tauri/Cargo.toml --lib g5_calls_are_route_closed_and_body_bounded_before_connecting` — 1 passou, 95 filtrados.
- `cargo fmt --all -- --check` — passou no diretório `apps/desktop/src-tauri`.
- `git diff --check` — passou após as alterações desta revisão.

A primeira chamada de `cargo fmt --all -- --check` foi feita em `apps/desktop`, que não contém `Cargo.toml`, e falhou com “could not find Cargo.toml”; a repetição no crate `src-tauri` passou. Uma checagem auxiliar de whitespace via `rtk python -c` também falhou porque o wrapper não encontrou esse comando; a mesma checagem foi repetida com `rtk node -e` e passou. A suíte Rust completa não foi executada. O binário release passou, mas não foi aberto e não prova o smoke da janela. Não houve conexão de conta, provedor, API paga nem acesso a dados externos. Nenhum daemon, serviço persistente do sistema ou dependência nova foi adicionado.

### Smoke manual pendente

O proprietário ainda precisa observar a janela real e registrar separadamente: (1) criação, timezone e próxima execução; (2) aviso e histórico após execução com o app aberto; (3) pause/resume/delete; (4) fechar o app antes do horário, reabrir e ver `missed`; (5) confirmar que a recuperação exige ação explícita e então verificar o resultado/histórico. Não marcar a UI como verificada a partir do build ou dos testes automatizados.

## Composição na candidata Phase 5 — 2026-10-13

Este handoff preserva a evidência reportada pela worktree de origem `feat/jarvis-automacoes-locais-persistentes`. A integração com workflow e Aprovações nativas está documentada em [`INTEGRATION_CANDIDATE_2026-10-13.md`](INTEGRATION_CANDIDATE_2026-10-13.md), que contém os comandos reexecutados na worktree composta, a prova `0019 → 0020` em banco temporário, os limites do SQLite sem cifra e os smokes manuais pendentes. Nenhuma janela foi observada; esta seção não transforma build/teste IPC em aceite visual.

## Contrato de erros — 2026-10-14

A candidata composta traduz os cinco códigos fechados de erro de automação para mensagens fixas em português, preservando a rejeição de códigos desconhecidos e campos extras. A reprodução, a correção, os testes sem janela e a decisão pendente sobre cifra em repouso estão em [LOCAL_AUTOMATION_ERRORS_2026-10-14.md](LOCAL_AUTOMATION_ERRORS_2026-10-14.md). Smoke manual permanece pendente.
