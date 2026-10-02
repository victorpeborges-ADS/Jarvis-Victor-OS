# Readiness e protocolo do helper de teste

## Transporte

O parent cria `current_exe()` diretamente com `std::process::Command`. stdin e stdout são pipes privados do child; stderr é descartado. O ambiente do child é limpo. Não há socket, porta ou endpoint HTTP.

O ID é criado para cada tentativa e acompanha todas as mensagens. A confirmação é igualdade textual exata depois de remover apenas `CR`/`LF`:

```text
child -> parent: JARVIS_RUNTIME_READY <runtime_instance_id>
parent -> child: JARVIS_RUNTIME_ACK <runtime_instance_id>
parent -> child: JARVIS_RUNTIME_STOP <runtime_instance_id>
```

O helper não passa ao estado de espera normal até consumir ACK com seu próprio ID. O parent ignora linhas com outro ID, ID anterior, prefixo parecido ou texto inválido. Mensagem de parada com ID divergente não encerra o helper.

## Identificador

O valor é derivado de PID do parent, nanossegundos desde Unix epoch e sequência atômica do processo. Ele evita confundir tentativas e permite correlação; não é aleatório criptográfico, senha ou credencial. O ID é exibido na área local e pode aparecer nos logs. Nenhum segredo ou conteúdo do produto é enviado pelo protocolo.

## Critério de readiness

O manager só reconhece uma linha completa que corresponda ao ID corrente. Após validação, escreve ACK no pipe; se não puder escrever, mata e recolhe o child e marca falha. Esta prontidão significa apenas que o helper sintético iniciou e concluiu o handshake local. Não significa API, SQLite, migrações, sessão, grants, origem web ou produto conectado.

Antes de READY, EOF do stdout não prova que o processo terminou. O supervisor continua observando seu `Child` até a saída ou o prazo de startup e continua aceitando STOP. Saída observada antes do prazo usa `child_exit_before_ready` e o código real; se o child ainda vive quando o prazo vence, ele é encerrado pelo próprio handle e a categoria é `readiness_channel_closed`. Veja [`PRE_READY_FAILURE_CONTRACT.md`](PRE_READY_FAILURE_CONTRACT.md).

## Restrições de entrada

- O frontend invoca comandos Tauri sem payload: `runtime_status`, `runtime_start_test`, `runtime_stop`, `runtime_restart_test`.
- O comando não aceita caminho de executável, argumentos, ambiente, porta ou ID vindos do frontend.
- Produção usa exclusivamente o modo `normal`. Modos adversariais e override de executável existem somente com `cfg(test)`.
- O binário reconhece apenas uma opção interna fixa, ID e modo tipado; argumentos extras ou modo desconhecido terminam com erro.
- Não há shell nem interpolação de comando.

## Limites

O ACK não autentica contra processos privilegiados no mesmo host. A garantia vem do pipe criado entre parent e child retido pelo handle; não existe promessa criptográfica contra administrador local. A API futura precisa de outro contrato de readiness que prove ownership do listener, endpoint e estado de DB antes de conectar o cliente.
