# Resultado de operação de stop — MAC-001.2

`stop_and_wait()` continua retornando `RuntimeSnapshot`, mas esse valor agora pertence à geração escolhida quando `begin_stop()` adquiriu o mutex de `Inner`. `snapshot()` e `runtime_status()` respondem outra pergunta: qual é o estado atual do manager.

| Estado no ponto de linearização | Resultado de `stop_and_wait()` |
|---|---|
| `STOPPED` | No-op `STOPPED`, sem ID alvo, ainda que B inicie antes do retorno. |
| `STARTING`, `READY` ou `STOPPING` de A | Snapshot terminal verdadeiro de A, preservando ID, PID, categoria e código de saída de A. |
| `FAILED` ou `CRASHED` de A | Transição imediata para `STOPPED` de A; o supervisor já recolheu o child. |
| A não conclui dentro do prazo | `CommandTimeout`; o supervisor conserva a obrigação de encerrar e recolher A. |

Um `Arc<GenerationCompletion>` é criado com cada geração. Ao concluir A, o supervisor publica seu snapshot terminal no objeto de A enquanto ainda detém o mutex de `Inner`; só depois B pode substituir o snapshot global. Waiters seguram o `Arc` de A, não uma referência ao estado corrente. A ordem de locks na publicação é `Inner` → `GenerationCompletion.result`; a espera usa só o mutex da conclusão, libera-o no `Condvar` e nunca adquire `Inner` enquanto o mantém. Não há mapa sem limite nem lock global entre managers.

O comando Tauri `runtime_stop` permanece assíncrono e sem payload: ele confirma a solicitação e devolve o snapshot observado na linearização. A UI não trata essa resposta como status corrente. Após qualquer comando, ela consulta `runtime_status` separadamente; se B já está READY, mostra B. Nenhum PID é autoridade de controle e nenhum handle bruto chega à UI.
