# Classificação antes de readiness — MAC-001.2

## Causa e regra

No baseline, `StdoutClosed` fazia um único `child.try_wait()`. EOF podia chegar ao supervisor antes de o processo finalizar; nessa janela, o supervisor matava o child e registrava `readiness_channel_closed`, mesmo quando o helper já estava saindo por conta própria. A ordem de agendamento alterava a categoria do mesmo cenário.

Agora EOF apenas marca que não haverá mais readiness pelo pipe. O supervisor conserva o handle e continua observando `try_wait()` até uma destas condições:

1. O child termina antes do prazo de startup: `FAILED/child_exit_before_ready`, com o código de saída real, inclusive zero.
2. O prazo de startup vence e o child ainda está vivo: o supervisor mata **esse child**, chama `wait()` e registra `FAILED/readiness_channel_closed`.
3. Chega STOP durante a agregação: o fluxo normal de stop encerra/recolhe o child e produz `STOPPED`.

O prazo é o timeout de startup já existente (5 s em produção; 450 ms nos testes). Não há sleep de correção nem mutex retido durante a espera. O `recv_timeout` de 10 ms já usado pelo supervisor mantém a recepção de STOP. `StdoutFailed` e falha de ACK conservam categorias próprias; readiness válida seguida de saída é `CRASHED`, não falha pré-ready.

O contrato classifica o estado observável **no momento da decisão**. Se o processo permanece vivo até o prazo, a categoria de canal fechado continua semanticamente distinta de uma saída observada antes de READY.
