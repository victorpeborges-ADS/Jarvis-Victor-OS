# G6-MAC-002 — Máquinas de estado

Runtime e transporte têm estados separados. Runtime `READY` não implica transporte `READY`.

```text
Runtime:
STOPPED → STARTING → READY → STOPPING → STOPPED
              ↘ FAILED  ↘ STOPPED (supervisor_lost)
                         ↘ CRASHED
FAILED / CRASHED → STOPPED → STARTING (somente reinício explícito)

Transport, por runtime_instance_id:
DISCONNECTED → DISCOVERING → PROVING_INSTANCE → READY
                                      ↘ INCOMPATIBLE
                                      ↘ FAILED
READY → DISCONNECTED (stop/reap ou supervisor_lost)
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

## Supervisor loss e concorrência de probes

O pipe herdado de controle representa ownership. O child inicia o leitor de controle logo após ler o registro de init. EOF em `STARTING` aborta o bind/readiness; EOF depois do ACK marca o runtime inativo, para de aceitar novas conexões, suprime resposta de request já em andamento e encerra com código interno `48`. O Runtime Manager reap o child, revoga a sessão e registra `supervisor_lost`. STOP escrito e reconhecido continua sendo encerramento normal, com código `0`.

Probes completos (`health → version → instance-proof`) são serializados pelo `request_lock` da sessão. Chamadas que concorram esperam esse lock. O primeiro probe que termina enquanto o snapshot ainda está em `PROVING_INSTANCE` publica seu resultado; um resultado posterior vê que o estado já mudou e é descartado. Se stop, EOF ou troca de geração invalidar a sessão antes do fim, o resultado tardio não altera o snapshot.

## Prazos e limites

- Connect UDS no macOS: 350 ms via socket não bloqueante + `poll`.
- Pedido/resposta client: 900 ms de prazo total por troca HTTP.
- Leitura de pedido do helper: 500 ms de prazo total.
- Header de resposta: 2.048 bytes; body de resposta: 2.048 bytes.
- Header de pedido: 1.024 bytes; body de pedido: 128 bytes.
- Rotas, método, Host e tamanho são allowlist fixa. `Transfer-Encoding`, Origin, credenciais e respostas duplicadas/malformadas são recusadas.
- Uma conexão UDS por request; não há keep-alive, pipeline, chunked nem proxy genérico. O parser aceita somente `HTTP/1.1`, um `Content-Length` válido e a resposta/request correspondente. Bytes extras já recebidos junto ao corpo enquadrado são rejeitados; nenhum socket é reutilizado para uma segunda resposta.

O limite atual é deliberadamente pequeno para o único probe sintético. MAC-003 precisa revisar esses limites para payloads do contrato real sem torná-los ilimitados.
