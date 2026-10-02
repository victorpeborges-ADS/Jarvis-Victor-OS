# Matriz de flakiness e concorrência — MAC-001.2

## Resultados observados

| Prova | Rodadas | Resultado |
|---|---:|---|
| Teste historicamente intermitente `child_exit_before_readiness_is_failed`, executável oficial chamado isoladamente | 1.000 | 1.000 passes, 0 divergências, 32,63 s. |
| Stress ignorado `pre_ready_exit_classification_1000_rounds` | 1.000 | 1.000 passes, 0 divergências, 22,61 s; alterna saída não zero e EOF seguido de saída. |
| Stress ignorado `stress_start_stop_race_1000_rounds` | 1.000 | PASS, 21,08 s; nenhum timeout espúrio, resultado de geração posterior ou supervisor residual. |
| Harness externa, fora da worktree, com cópia do runtime e probe próprio | 1.000 | PASS, 16,89 s; zero resultado de geração errada, timeout ou supervisor residual. Log: `/private/tmp/jarvis-g6-mac001-2-independent-20261002/stress.log`. |
| Suíte integral `cargo test --locked` após atualização dos testes | 20 | 20/20 verdes; cada rodada: 42 passes, 4 ignored, 0 failures; 36,52 s. |
| Cliente: resultado de stop A seguido de status B | 1 | PASS com `node --test apps/desktop/tests/runtimeCommand.test.mjs`. |

Antes de atualizar as asserções herdadas de MAC-001.1, uma execução da suíte com o novo código teve 32 passes, **2 failures** e 3 ignored: os dois testes A→B ainda exigiam o retorno incorreto de B. As asserções foram corrigidas para exigir o snapshot terminal de A. Essa falha intermediária não foi tratada como verde nem apagada pela repetição.

## Casos determinísticos

- `STOPPED` → start B antes do retorno: no-op sem ID; B pertence ao start posterior.
- `READY(A)` ou `STARTING(A)` → stop A → start B → B READY: retorno `STOPPED(A)`, status B READY.
- `READY(A)` → stop A → B ainda STARTING: retorno `STOPPED(A)`, status B STARTING.
- `READY(A)` → stop A → B CRASHED: retorno `STOPPED(A)`, status B CRASHED.
- Target A ignora STOP: `CommandTimeout` real, seguido de encerramento/reap pelo supervisor.
- Saída antes de readiness com código 41, 47 ou 0: `child_exit_before_ready` e código real.
- EOF com child vivo até o prazo: `readiness_channel_closed`.
- STOP durante agregação de EOF: `STOPPED`, child recolhido.
- Readiness válida seguida de saída: `CRASHED`, sem reclassificação pré-ready.
- Eventos tardios A→B, dois managers, processo alheio, start/start, stop/stop e restart concorrente: cobertos pela suíte oficial; nenhuma ampliação de superfície de comando.

Os dois stresses ignorados são invocados explicitamente. Os outros ignored são o entrypoint do helper sintético e o smoke do executável release, que deve rodar após o build nativo.
