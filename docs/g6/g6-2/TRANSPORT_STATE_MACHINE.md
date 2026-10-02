# G6-MAC-002 — Máquinas de estado

Runtime e transporte têm estados separados. Runtime `READY` não implica transporte `READY`.

```text
Runtime:
STOPPED → STARTING → READY → STOPPING → STOPPED
              ↘ FAILED        ↘ CRASHED
FAILED / CRASHED → STOPPED → STARTING (somente reinício explícito)

Transport, por runtime_instance_id:
DISCONNECTED → DISCOVERING → PROVING_INSTANCE → READY
                                      ↘ INCOMPATIBLE
                                      ↘ FAILED
READY → DISCONNECTED (stop/reap)
qualquer estado ativo → FAILED (crash, resposta inválida ou timeout)
```

| Estado | Significado |
|---|---|
| `DISCONNECTED` | Não há sessão de transporte utilizável. |
| `DISCOVERING` | Runtime Manager reservou endpoint UDS da geração. Ainda não foi provado. |
| `PROVING_INSTANCE` | Child anunciou readiness; native client verifica health, versão e prova HMAC. |
| `READY` | Prova e operação sintética foram validadas para o ID esperado. |
| `INCOMPATIBLE` | Runtime kind, build ou versão do protocolo fora do contrato. |
| `FAILED` | Endpoint indisponível, prova incorreta, resposta malformada, timeout ou limite excedido. |

O ID da geração acompanha as duas máquinas. Cada chamada nativa captura a sessão da geração sob o lock do Runtime Manager. A chamada não busca uma sessão substituta durante I/O. Stop invalida a capacidade antes de liberar a chamada de encerramento; se o child ainda está iniciando, o path fica até ele consumir STOP e ser reapado. O supervisor mantém ownership do child conforme MAC-001.

## Prazos e limites

- Connect UDS no macOS: 350 ms via socket não bloqueante + `poll`.
- Pedido/resposta client: 900 ms de prazo total por troca HTTP.
- Leitura de pedido do helper: 500 ms de prazo total.
- Header de resposta: 2.048 bytes; body de resposta: 2.048 bytes.
- Header de pedido: 1.024 bytes; body de pedido: 128 bytes.
- Rotas, método, Host e tamanho são allowlist fixa. `Transfer-Encoding`, Origin, credenciais e respostas duplicadas/malformadas são recusadas.

O limite atual é deliberadamente pequeno para o único probe sintético. MAC-003 precisa revisar esses limites para payloads do contrato real sem torná-los ilimitados.
