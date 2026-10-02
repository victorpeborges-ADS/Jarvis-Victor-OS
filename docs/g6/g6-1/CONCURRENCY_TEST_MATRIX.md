# Matriz de concorrência — G6-MAC-001.1

## Testes determinísticos

| Caso | Teste/evidência | Asserção principal |
|---|---|---|
| Stop em `STOPPED` | `stop_and_wait_when_stopped_is_an_immediate_noop` | Sucesso/no-op, sem supervisor. |
| Stop observa `STOPPED`; start ocorre antes do retorno | `stopped_stop_does_not_adopt_a_concurrent_future_start` | Stop retorna o snapshot no-op; a nova geração continua ativa até stop próprio. |
| Stop de A em `READY`; B nasce antes da espera de A continuar | `stop_of_ready_generation_does_not_wait_for_or_stop_a_new_generation` | Resultado não tem timeout; B continua `READY` com supervisor. |
| Stop de A em `STARTING`; B nasce antes da espera de A continuar | `stop_of_starting_generation_does_not_wait_for_a_new_generation` | Espera fica vinculada ao ID A; B continua ativa. |
| Stop/stop | `concurrent_stop_calls_wait_for_the_same_generation` | Ambos concluem sobre o mesmo ID; child reaped. |
| Start/start | `concurrent_start_calls_create_only_one_child` | Uma chamada aceita, uma `InvalidState`, um child/supervisor. |
| Start/stop | `start_stop_race_leaves_no_child_or_supervisor` e stress abaixo | Resultados das duas threads verificados; cleanup e ownership confirmados. |
| Restart/stop | `restart_racing_stop_has_explicit_results_and_cleans_its_target` | Restart é aceito antes do stop do novo ID ou rejeitado depois do stop do estado anterior; sem resultado descartado. |
| Restart/restart | `concurrent_restarts_allow_exactly_one_new_generation` | Um restart aceito; outro `InvalidState`. |
| Eventos tardios A → B | `late_events_from_generation_a_cannot_change_generation_b` | READY, startup failure, runtime failure, STOPPED e exit de A não alteram B. |
| Timeout legítimo | `stop_timeout_remains_an_error_for_its_still_active_target` | Target correto ativo retorna `CommandTimeout`; o supervisor depois encerra e reaped o child. |
| Dois managers | `stopping_one_manager_does_not_stop_another_managers_child` | IDs/PIDs independentes; parar A preserva B. |
| Processo alheio | `unrelated_process_survives_start_stop_and_restart` | Helper independente sobrevive ao ciclo do manager. |

Os testes existentes também cobrem readiness correta/errada/stale/duplicada, crash antes/depois de readiness, stop durante startup, stop de child pronto, shutdown travado, cleanup na saída normal e prova do executável release.

## Stress separado

`runtime_manager::tests::linearization_tests::stress_start_stop_race_500_rounds` é ignorado na suíte normal para manter a suíte unitária rápida e deve ser chamado explicitamente:

```sh
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml \
  runtime_manager::tests::linearization_tests::stress_start_stop_race_500_rounds \
  -- --ignored --exact --nocapture --test-threads=1
```

Cada rodada usa um manager novo e inicia start/stop em barreira comum. O teste confere os dois resultados, que o stop não capture o ID iniciado depois do no-op, no máximo uma geração/supervisor por manager e ausência de child/supervisor após cleanup. Resultado da execução final desta candidata: **500/500 passaram em 11,72 s**, sem timeout, panic, deadlock ou child residual.
