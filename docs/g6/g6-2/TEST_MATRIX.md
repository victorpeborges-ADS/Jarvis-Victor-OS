# G6-MAC-002 — Matriz de testes

Resultados nesta candidata; o resumo final e os comandos executados estão em [G6_MAC_002_REPORT.md](G6_MAC_002_REPORT.md).

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
| Runtime crash / pipe de readiness / stop/reap | Suítes MAC-001 incluídas em `cargo test`; falhas pre-ready e pós-ready continuam exercitadas. | PASS na rodada integral: 55 aprovados, 0 falhos. |
| Executável Tauri release real | `release_tauri_binary_is_spawned_and_reaped`, execução explícita do teste antes ignorado. | PASS: readiness, prova, protocolo 1, pedido sintético, stop e reap. |
| Segredo/path ausentes do IPC tipado | `runtimeCommand.test.mjs` valida estado sem campos secret/socket path e rejeita endpoint tcp. | PASS esperado. |
| Proxy arbitrário não exposto | Inspeção estática dos comandos em `lib.rs` e assinatura sem args do probe. | Nenhum comando `http_request`, URL, método, headers ou path da UI. |
| TCP, portas 3000/8000 | Inspeção de bind e verificação pós-teste com ferramentas locais. | Zero listener TCP MAC-002; portas permanecem livres. |

Cinco testes permanecem marcados `ignored` na rodada padrão: dois probes de stress herdados da MAC-001, entrypoint filho de teste, processo fake spawnado pelo teste adversarial e o teste de binário release. O teste do binário release foi executado explicitamente e passou. A candidata não depende dos probes de stress para a evidência MAC-002.
