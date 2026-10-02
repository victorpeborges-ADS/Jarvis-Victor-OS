# Contrato de linearização de stop — G6-MAC-001.1

## Escopo

Este contrato corrige somente a concorrência do supervisor sintético local MAC-001. `runtime_instance_id` já identifica cada geração e é usado como chave de geração; não foi introduzido contador global nem lock entre managers.

## Ponto de linearização

`begin_stop()` observa o estado e captura o `runtime_instance_id` sob `Inner`'s mutex. Para `STARTING` e `READY`, também enfileira `SupervisorMessage::Stop` no canal do supervisor correspondente antes de liberar esse mutex. Como start/restart publica a geração atual sob o mesmo mutex, nenhuma geração posterior pode ser escolhida acidentalmente pelo stop.

| Estado observado no ponto de linearização | Resultado |
|---|---|
| `STOPPED` | Retorna o snapshot observado como sucesso/no-op. Um start posterior é outra operação e não muda esse retorno. |
| `FAILED` ou `CRASHED` | Transiciona para `STOPPED` sob o mesmo lock e retorna; o child já foi encerrado e reaped pelo supervisor. |
| `STARTING` ou `READY` | Captura o ID atual, envia STOP ao canal da geração capturada e espera somente por esse ID. |
| `STOPPING` | Captura o ID que já está sendo parado e espera somente por ele; não duplica o pedido. |

## Espera e timeout

A espera não mantém o mutex: `Condvar::wait_timeout` libera o lock durante a espera. MAC-001.2 guarda a conclusão terminal em um objeto da geração capturado por `begin_stop()`. Mesmo se B substituir A no status global, `stop_and_wait(A)` retorna o snapshot terminal verdadeiro de A, sem enviar STOP, aguardar ou matar B. Consulte [`OPERATION_RESULT_CONTRACT.md`](OPERATION_RESULT_CONTRACT.md).

`CommandTimeout` continua sendo erro quando a geração alvo não registrou conclusão terminal ao vencer o prazo. O timeout não é convertido em sucesso. O mecanismo do supervisor para shutdown timeout continua podendo encerrar e recolher o child retido.

## Eventos tardios

Readiness e eventos de saída/falha já são aplicados com igualdade exata do `runtime_instance_id` e do estado esperado. Os testes MAC-001.1 exercitam readiness, falha de startup, falha pós-readiness e exit atrasados da geração A depois que B é atual; nenhum deles pode alterar o snapshot B.

## Locks e hooks

O envio usa `std::sync::mpsc` não limitado e não aguarda o child, I/O ou callback com o mutex de estado retido. A conclusão usa outro mutex/condvar por geração; a ordem de publicação é `Inner` → conclusão, e o waiter usa somente conclusão. Hooks com barreiras existem somente sob `cfg(test)`.
