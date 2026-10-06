# G6-MAC-002.1 — Matriz de testes

Resultados desta candidata; comandos e evidências estão em [G6_MAC_002_1_REPORT.md](G6_MAC_002_1_REPORT.md).

| Cenário | Probe/evidência | Resultado esperado |
|---|---|---|
| Child real spawn → readiness → UDS → prova → versão → pedido sintético → stop/reap | `stopped_starting_ready_stopping_stopped` aguarda ambas as máquinas e verifica UDS/protocolo. | PASS: transport só `READY` após prova; stop termina em `DISCONNECTED`, child e supervisor são limpos. |
| Processo falso separado, health/version HTTP 200 corretos, sem capacidade | `fake_health_and_version_process_without_capability_is_rejected` executa outro processo de teste que serve UDS. | PASS: `proof_rejected`. |
| Processo falso cai durante o pedido de prova | `fake_runtime_crashing_during_proof_request_fails_closed`. | PASS: EOF/malformed response, sem `READY` autenticado. |
| HMAC incorreto | `wrong_proof_and_replayed_proof_are_rejected`. | PASS: rejeitado. |
| Replay com nonce antigo | Mesmo teste, resposta HMAC válida para nonce anterior fixo. | PASS: rejeitado. |
| Outro Manager A/B em READY | `separate_managers_and_stale_generations_cannot_cross_authenticate`. | PASS: A rejeita B e B rejeita A; B permanece pronto após stop de A. |
| Endpoint e geração A após stop | Mesmo teste, chamada à sessão A retida. | PASS: `generation_inactive`; nenhuma troca para B. |
| Probe atrasado após invalidação pelo stop | `late_probe_result_cannot_restore_transport_after_stop_invalidation`. | PASS: resultado assíncrono não altera `DISCONNECTED`. |
| Versão de protocolo incompatível | `incompatible_protocol_is_rejected_before_proof`. | PASS: `INCOMPATIBLE`. |
| Campos/resposta HTTP malformados ou conexão fechada | `malformed_oversized_slow_and_closed_responses_fail_closed`. | PASS: rejeitados, sem fallback. |
| Host não permitido e Origin de browser | `helper_requires_fixed_host_and_rejects_browser_origin_without_cors`. | PASS: HTTP 400; sem `Access-Control-Allow-Origin`. |
| Body de resposta acima de 2 KiB | Mesmo teste. | PASS: `response_too_large`. |
| Resposta além de 900 ms | Mesmo teste mede prazo. | PASS: timeout limitado. |
| Runtime crash / pipe de readiness / stop/reap | Suítes MAC-001 incluídas em `cargo test`; falhas pre-ready e pós-ready continuam exercitadas. | PASS na rodada integral, incluída no total final abaixo. |
| Executável Tauri release real | `release_tauri_binary_is_spawned_and_reaped`, execução explícita do teste antes ignorado. | PASS: readiness, prova, protocolo 1, pedido sintético, stop e reap. |
| EOF em STARTING / READY | `supervisor_eof_during_starting_fails_without_readiness`, `supervisor_eof_after_ready_revokes_capability_and_reaps_child`. | PASS: failure/Stopped com `supervisor_lost`, sem READY após EOF, capability revogada e child reapado; testes exigem saída em menos de 350 ms. |
| EOF durante proof e request | `supervisor_eof_during_proof_request_closes_child_without_late_response` e probe com EOF enquanto o body está incompleto. | PASS: conexão fecha sem resposta tardia, sessão torna-se inativa e child encerra. |
| STOP + EOF, observação repetida de EOF e morte do parent | `eof_and_stop_race_is_idempotent`, `repeated_supervisor_loss_observation_is_idempotent`, `hard_parent_loss_closes_inherited_control_pipe_and_child_exits_bounded` e encerramento repetido. | PASS: shutdown/reap idempotentes, sem panic, capability removida; código 0 para STOP e 48 para perda do supervisor. |
| Path trocado antes do bind | Matriz de file, symlink para file/diretório, diretório novo e socket falso; `startup_path_replacement_types_fail_closed_before_bind`. | PASS: nenhum READY, falha fechada e canários externos preservados. |
| Path trocado após bind / cleanup do child e parent | `cleanup_after_bind_and_renamed_parent_preserves_external_canaries`, `child_drop_after_parent_rename_preserves_external_canaries`, `cleanup_is_anchored_to_original_directory_across_replacement_matrix`. | PASS: socket removido apenas relativo ao FD original; canários externos permanecem byte a byte. |
| Canários e ataques repetidos | `stress_path_substitution_200_rounds`, `stress_child_startup_path_substitution_200_rounds`. | PASS: 200 ciclos por probe, 0 remoções externas, 0 READY falso, 0 child residual. |
| EOF repetido após READY | `stress_supervisor_eof_200_rounds`. | PASS: 200 ciclos, child encerra, sessão revogada e reap concluído. |
| Lifecycle normal | `stress_normal_transport_lifecycle_500_rounds`. | PASS: 500 ciclos spawn → prova → pedido → stop → cleanup. |
| Stop/start e classificação pre-ready MAC-001 | `stress_start_stop_race_1000_rounds`, `pre_ready_exit_classification_1000_rounds`. | PASS: 1.000 ciclos em cada stress, sem regression observada. |
| Framing HTTP subset | `response_http_framing_subset_rejects_malformed_and_extra_bytes`. | PASS: malformed CRLF, bytes extras, headers duplicate/conflitantes, body truncado, Content-Length inválido, Transfer-Encoding e limites excedidos são rejeitados. |
| Probes concorrentes | `concurrent_probes_are_serialized_and_publish_first_completed_result`. | PASS: `request_lock` serializa a sequência health → version → proof; o primeiro probe concluído publica enquanto a geração segue `PROVING_INSTANCE`; resultados posteriores ou invalidados não sobrescrevem estado. |
| Segredo/path ausentes do IPC tipado | `runtimeCommand.test.mjs` valida estado sem campos secret/socket path e rejeita endpoint tcp. | PASS esperado. |
| Proxy arbitrário não exposto | Inspeção estática dos comandos em `lib.rs` e assinatura sem args do probe. | Nenhum comando `http_request`, URL, método, headers ou path da UI. |
| TCP, portas 3000/8000/1420 | Inspeção de bind e verificação pós-teste com ferramentas locais. | Zero listener TCP MAC-002; portas permanecem livres. |

Rodada padrão final: 69 aprovados, 9 ignorados, 0 falhos. Os nove ignorados são dois entrypoints subprocessados (`runtime_helper_entry`, `fake_runtime_process_entry`), o teste de binário release e seis stresses: dois MAC-001 e quatro MAC-002. Os entrypoints são executados por seus testes controladores; os outros sete testes ignored foram invocados explicitamente. O build release Tauri sem bundle também passou.
