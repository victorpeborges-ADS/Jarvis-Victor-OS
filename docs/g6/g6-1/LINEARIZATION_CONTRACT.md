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

A espera não mantém o mutex: `Condvar::wait_timeout` libera o lock durante a espera. Enquanto o snapshot ainda contém o ID-alvo em estado ativo, a operação continua aguardando. Se esse ID terminar, ou se um ID diferente se tornar atual, a operação retorna o snapshot corrente sem enviar STOP, aguardar ou matar a geração nova. Um ID diferente só pode ser publicado depois que a transição/reaping da geração anterior permitiu start ou restart.

`CommandTimeout` continua sendo erro quando o snapshot ainda é ativo e contém o mesmo ID-alvo ao vencer o prazo. O timeout não é convertido em sucesso. O mecanismo do supervisor para shutdown timeout continua podendo encerrar e reaped o child retido.

## Eventos tardios

Readiness e eventos de saída/falha já são aplicados com igualdade exata do `runtime_instance_id` e do estado esperado. Os testes MAC-001.1 exercitam readiness, falha de startup, falha pós-readiness e exit atrasados da geração A depois que B é atual; nenhum deles pode alterar o snapshot B.

## Locks e hooks

O lock de estado continua sendo o único lock de produção neste fluxo. O envio usa `std::sync::mpsc` não limitado e não aguarda o child, I/O ou callback com o mutex retido. Hooks com barreiras usados para tornar interleavings determinísticos existem somente sob `cfg(test)`; não ampliam a superfície de produção.
