# MAC-002.1 — Contrato de perda do supervisor

## Ownership

O pipe privado herdado (`stdin`) é o canal de ownership da geração. O child lê o registro de inicialização e então inicia um leitor único para ACK, STOP e EOF. O ACK autoriza prosseguir depois do sinal de readiness; EOF permanente significa que o owner desapareceu. O child não reinicia nem continua em modo autônomo.

## Transições

| Momento | Sinal | Resultado no child | Resultado no Runtime Manager |
|---|---|---|---|
| `STARTING`, antes do anúncio | EOF | Abort startup e cleanup; não escreve `READY`; exit interno 48. | `FAILED`, `failure_category=supervisor_lost`; capability revogada e child reapado. |
| `STARTING`, depois do anúncio mas antes do ACK | EOF/ACK impossível | O supervisor não publica `READY` antes de conseguir escrever ACK. Sem ACK, mata/reap e falha a geração. | `FAILED`, sem `ready_at_unix_ms`; não inicia prova. |
| `READY`, sem request ativo | EOF | Marca o canal inativo, para de aceitar requests, remove o socket e sai com código 48. | `STOPPED`, `failure_category=supervisor_lost`, transporte `DISCONNECTED`; capability removida e processo reapado. |
| Request/probe em andamento | EOF | Marca inativo imediatamente. O request pode terminar de ler até seu deadline; uma resposta calculada depois da invalidação é descartada antes da escrita. O child encerra. | Resultado tardio não publica `READY` nem troca a geração. |
| Qualquer estado ativo | STOP com ID correto | Encerramento controlado normal, exit 0. STOP e EOF são sinais distintos. | `STOPPING → STOPPED`; cleanup idempotente. |

O código interno 48 não contém segredo nem é apresentado como erro de produto. Em `STOPPING`, STOP/EOF concorrentes continuam produzindo um único reap e um único resultado terminal; se o processo saiu por EOF, o diagnóstico `supervisor_lost` é preservado.

## Prazo

O leitor de controle sinaliza EOF por canal e flag atômica, sem polling com sleep como mecanismo de sincronização. O loop de accept verifica a flag em intervalos máximos de 10 ms. Uma leitura de request já aceita tem deadline de 500 ms; por isso a saída normal sem request é observada rapidamente e a saída durante request fica limitada pelo término/timeout dessa leitura mais o agendamento do sistema. Os testes medem saída abaixo de 350 ms sem request e abaixo de 1 s durante proof parcial.

## Evidência

- `supervisor_eof_during_starting_fails_without_readiness`
- `supervisor_eof_after_ready_revokes_capability_and_reaps_child`
- `supervisor_eof_during_proof_request_closes_child_without_late_response`
- `eof_and_stop_race_is_idempotent`
- `hard_parent_loss_closes_inherited_control_pipe_and_child_exits_bounded`
- `stress_supervisor_eof_200_rounds`

O harness de hard loss fecha o pipe como ocorreria quando o parent morre e comprova que o child termina sem receber STOP. Não se promete cleanup após SIGKILL do próprio child ou quando o kernel não entrega EOF observável ao descritor herdado.
