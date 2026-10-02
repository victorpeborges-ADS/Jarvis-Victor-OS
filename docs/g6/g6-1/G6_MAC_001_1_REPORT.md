# G6-MAC-001.1 — relatório de linearização de stop

## Identificação e decisão

- Branch: `feat/jarvis-g6-mac-001-1-linearized-stop-2026-10-02`
- Baseline exato: `c6fc5b9288e4569be8de95a4069c79eadce13f3f`
- Commit de implementação: `aee1aed8a7d9a35de0694af8e1dff75e1bb3c430`
- Commit de testes: `3b6fe7dc3ec4462896b1723c849359f111ced82f`
- G6.0: `59c3b28103bef2fb0ce518826bcca834b43dccd2`
- `main` observada: `82b3c244c796b68b181dbf127509caababd2258e`
- G5 aceito: `ab7f856ee834b7f9923d914639e0e345dbf57322`
- Escopo: somente semântica concorrente de `stop`/`stop_and_wait` do helper sintético local MAC-001.
- Decisão da implementação: candidata pronta para reauditoria independente de MAC-001.1; isto não é aceite formal de G6.1 e não inicia MAC-002.
- Toolchain: `rustc`/`cargo` 1.99.0, `rustup` 1.29.1, Node v26.7.0, npm 11.19.0. Sem atualizações.

## Arquivos desta correção

- `apps/desktop/src-tauri/src/runtime_manager.rs`
- `apps/desktop/src-tauri/src/runtime_manager/tests/runtime_manager_linearization_tests.rs`
- `docs/g6/BACKLOG.md`
- `docs/g6/g6-1/G6_MAC_001_1_REPORT.md`
- `docs/g6/g6-1/LINEARIZATION_CONTRACT.md`
- `docs/g6/g6-1/CONCURRENCY_TEST_MATRIX.md`
- `docs/g6/g6-1/RESUME_MAC_001_1.md`

O frontend e o backend não mudaram; não há captura de UI nesta correção de semântica interna.

## Reprodução independente do P2 no baseline

O código congelado do SHA base reproduziu o defeito com uma harness temporária fora da worktree. A harness usou cópia do `runtime_manager.rs` do SHA exato e um hook de barreira exclusivamente de instrumentação para ordenar: stop captura `STOPPED`; a barreira pausa; start cria uma geração; stop continua para a espera do código-base. O probe observou `CommandTimeout` do stop antigo enquanto o novo child permanecia ativo. O cleanup explícito posterior parou e reaped o child, sem perda de ownership.

Uma execução sem instrumentação de 32 corridas start/stop passou, consistente com o achado intermitente da auditoria anterior. O teste com barreiras transforma a janela estreita em uma reprodução determinística, sem alterar o SHA auditado.

## Causa raiz e correção

No SHA base, `stop_and_wait()` chamava `request_stop()` e, após essa chamada liberar o lock, adquiria o lock novamente e esperava enquanto qualquer geração atual estivesse ativa. Se o primeiro stop fosse um no-op em `STOPPED`, um `start()` posterior podia ser adotado pela espera antiga.

MAC-001.1 introduz `begin_stop()`: o ponto de linearização captura estado e `runtime_instance_id` sob o mutex de `Inner`; para `STARTING`/`READY`, enfileira STOP no canal daquela geração antes de soltar o lock. `stop_and_wait()` espera apenas enquanto o ID capturado continua atual e ativo. Se outro ID se tornar atual, a geração-alvo já encerrou/reaped o bastante para permitir start/restart; a operação retorna sem aguardar ou afetar a nova geração. `STOPPED` retorna o snapshot capturado como no-op imediato. O contrato completo está em [`LINEARIZATION_CONTRACT.md`](LINEARIZATION_CONTRACT.md).

A espera continua fora do lock e usa `Condvar::wait_timeout`, que libera o mutex. O timeout só é retornado quando o mesmo ID-alvo permanece ativo no vencimento. Uma prova mantém esse timeout como erro para um target realmente travado. O ID existente é suficiente; nenhum contador global ou lock entre managers foi adicionado. Barreiras de teste estão restritas a `cfg(test)`.

## Cobertura e validação

| Verificação | Resultado |
|---|---|
| `npm run build --prefix apps/desktop` | PASS, exit 0. |
| `cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS, exit 0. |
| `cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS, exit 0, sem warning. |
| `cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS: 34 passaram, 0 falharam, 3 ignorados. |
| Stress `stress_start_stop_race_500_rounds` | PASS: 500/500, 11,72 s; sem timeout, panic, deadlock ou child residual. |
| `release_tauri_binary_is_spawned_and_reaped` ignored, invocado explicitamente | PASS: 1 passou; binário release fez READY/stop/reap. |
| `npm --prefix apps/desktop run tauri -- build --no-bundle` | PASS, 3 min 19 s; executável `target/release/desktop` gerado. Sem bundle, assinatura ou notarização. |
| Readiness e crashes | PASS na suíte: readiness correta, errada/stale/duplicada/inválida, saída antes/depois e canal fechado. |
| Ownership | PASS: processo sintético independente sobrevive; dois managers preservam os respectivos children. |
| Eventos tardios A → B | PASS: readiness/falha/exit de A não sobrescrevem o snapshot B. |
| Timeout legítimo | PASS: target ativo em `STOPPING` retorna `CommandTimeout`; o supervisor depois o encerra/reap. |

A matriz de cenários está em [`CONCURRENCY_TEST_MATRIX.md`](CONCURRENCY_TEST_MATRIX.md). `cargo test` mantém ignorados o entrypoint usado como child sintético, o smoke do release e o stress de 500 rodadas; os dois últimos foram executados separadamente nesta entrega.

## Integridade e limites

O diff desta branch parte diretamente de `c6fc5b9288e4569be8de95a4069c79eadce13f3f`. `apps/api`, migrações, ADR-010, contratos G5, knowledge/provenance e lockfiles permanecem sem diff. Por isso a regressão completa da API não foi repetida; G5 não foi revalidado nem reaceito aqui.

Não há integração FastAPI/SQLite, socket ou mudança em CORS/CSP/Origin/Host/CSRF. Os probes de helper não abriram listener; portas 3000/8000 permanecem livres. A saída normal do aplicativo e os casos de shutdown já cobertos pela suíte continuam verdes. O teste mantém ownership local monoprocesso; não cria exclusão global entre múltiplas instâncias. `SIGKILL` continua fora da garantia.

Não houve redesign/UI nova, serviço persistente, dependência adicionada, merge, push, tag ou deploy. G6-MAC-002 não foi iniciado. A decisão de aceite cabe à auditoria independente e ao proprietário.
