# Executor local de workflows tipados

Estado desta candidata: implementação local em revisão. Não representa aceite formal de G5, MAC-002.2 ou MAC-003, nem habilita distribuição.

## Política e catálogo

O modelo, quando houver um provider configurado, pode recomendar apenas `tool_id` e argumentos. A API valida o objeto com schemas Pydantic fechados (`extra=forbid`) e política determinística. Cada `ToolSpec` declara schema, permissão, risco, timeout, limite por execução, retry e efeito esperado. Não há rota para método, URL, shell, comando ou headers fornecidos pelo modelo.

Executáveis nesta fase:

- `draft_note`: grava uma proposta de texto no registro durável da tarefa. Exige sessão G5 ativa, não exige grant de revisão e não chama rede ou modelo.
- `simulate_action`: usa apenas o serviço/conta/alvo sintéticos fixos (`synthetic-mail`, `operator@example.test`, `synthetic-outbox`). Mostra serviço, conta, alvo, payload completo, consequência e `data_sent=[]`. Uma janela de confirmação nativa precede a simulação; o backend registra `sent=false`.

`send_message`, `pay`, `delete_record` e `invite_member` existem somente como entradas explicitamente desabilitadas do catálogo. O policy engine as recusa antes de criar uma tarefa. Nenhuma ferramenta externa possui implementação nesta fase.

## Entrada nativa da passphrase G5

A WebView não coleta, armazena nem envia a passphrase. `g5_session_open` não aceita argumentos IPC; no macOS, o comando Rust abre um diálogo nativo com campo oculto por meio de `/usr/bin/osascript`, chamado diretamente sem shell. O script e os argumentos do processo são estáticos e não incluem o segredo. A saída padrão é capturada em memória, `stderr` é descartado, e os bytes passam por `SecretBytes` antes de serem convertidos para `SecretText`, que é zerado ao sair de escopo. Cancelamento, falha do processo ou saída malformada retornam mensagens fixas sem ecoar dados. Em sistemas sem a entrada nativa macOS, o comando falha fechado. Testes cobrem o parser com valores sintéticos; nenhum diálogo real foi aberto nesta revisão.

## Aprovação G5

A WebView não recebe token de sessão, CSRF ou ID de grant. Só invoca comandos Tauri tipados; para simular, o Rust busca a tarefa pelo UDS, exibe a prévia completa em diálogo nativo, confirma que o hash ainda é o mesmo, e então chama a rota fixa de aprovação e execução.

O servidor mantém o lock de grant antes do SQLite. A aprovação dura 60 segundos, inclui hash canônico dos parâmetros, grant exato e um HMAC opaco do token de sessão com chave efêmera do processo. O token em claro não é persistido. No instante de executar, sessão, grant, validade, hash e uso único são revalidados; a reserva da aprovação e a transição para `running` são uma transação SQLite `BEGIN IMMEDIATE`. HMAC da sessão muda a cada reinício, e grants/sessões também são voláteis; uma tarefa interrompida exige novo consentimento e nova concessão antes de ser retomada.

Revogar `mission:review` usa uma rota UDS fixa e invalida a autorização antes de qualquer execução subsequente. A pausa de uma tarefa em espera consome a aprovação pendente; retomá-la requer nova confirmação. Tarefas interrompidas não retomam silenciosamente uma simulação. Tarefas concluídas têm resultado canônico com SHA-256 verificado na leitura; uma repetição com a mesma sessão/grant devolve o resultado gravado sem repetir o efeito.

## Estados e limites

Estados persistidos: `proposed`, `awaiting_approval`, `paused`, `running`, `interrupted`, `succeeded`, `failed` e `cancelled`. A inicialização do FastAPI converte execuções abertas em `interrupted`. Para as duas ferramentas locais, repetir após crash é seguro porque o rascunho é parte do registro e a simulação não tem efeito fora do banco. Nenhuma decisão de retry se baseia no LLM.

A chamada histórica `/v1/app/workflows/list` continua entregando no máximo quatro tarefas por `updated_at DESC, id`, com os mesmos campos. A nova operação paginada descrita abaixo percorre o histórico por criação, sem mudar o contrato de consumidores antigos.

Timeouts são aplicados às funções locais em worker limitado; retries são limitados ao erro local transitório declarado. O limite atual é um item por execução. Cancelamento impede iniciar uma tarefa em estado cancelado; ferramentas longas e cancelamento cooperativo durante I/O ainda não existem. Não há execução de I/O externo para interromper.

Logs persistem somente eventos enumerados e timestamps; não contêm argumentos, payloads, tokens ou respostas. O SQLite local armazena os argumentos necessários à durabilidade e à prévia, além do resultado; esta fase não cifra o conteúdo do banco. Não inclua credenciais, tokens ou dados que não queira manter localmente. Marcadores comuns de credenciais são recusados, mas isso não substitui classificação do conteúdo pelo usuário.

Migração: `apps/api/migrations/0019_workflow_tasks.sql`. O número 0019 evita colisão com migrações 0017/0018 presentes em candidatas paralelas. Esta candidata não combina essas worktrees; qualquer composição futura deve auditar e reconciliar o grafo das migrações antes de integrar.

## Verificações desta candidata

Os testes devem cobrir schema fechado, ferramentas bloqueadas, alteração de parâmetros, replay concorrente, expiração/revogação de grant, reinício e crash, retry, resposta perdida, hash de resultado, cancelamento e ausência de payload nos logs. O teste Rust de integração usa FastAPI real supervisionado via UDS e dados sintéticos. Build e testes automatizados não substituem smoke da janela Tauri real; nenhuma verificação visual manual está alegada por este documento.


## Paginação explícita do histórico — 2026-10-14

Contrato aditivo: `POST /v1/app/workflows/page`, pedido com **exatamente**, nesta ordem, `session_token` e `cursor`; sucesso com `ok=true`, `tasks_json` e `next_cursor`. IPC dedicado `g5_workflow_page(cursor)` e cliente TypeScript `workflowPage(cursor="")`. A WebView recebe apenas resumos e cursor; token permanece no Rust. Cada leitura exige sessão G5 ativa sob o lock existente. Cursor é navegação, nunca autorização. Não aceita limite, offset, filtro, método ou rota arbitrários.

A primeira consulta usa cursor vazio. Ordem keyset: `created_at DESC, id DESC`; a próxima consulta aplica `(created_at,id) < (data,id)` da última linha entregue. Ambos são imutáveis no executor. Estado e `updated_at` podem mudar sem mover itens entre páginas. Empates de criação são resolvidos pelo ID. Cursor canônico `wf1|<created_at UTC ISO>|<id hexadecimal minúsculo de 32 caracteres>`: até 80 bytes ASCII, data válida, segundos e opcionalmente seis dígitos de microssegundos **não todos zero**, deslocamento `+00:00`. Framing/percent-encoding e campos extras continuam recusados; cursor inválido recebe `schema_rejected`, sem eco.

No máximo quatro resumos por resposta; o backend lê no máximo cinco linhas para detectar continuação. A quantidade pode ser menor pelo orçamento de bytes. O empacotamento mede a resposta textual ASCII já percent-encoded **incluindo `ok`, JSON, cursor, nomes e quebras de linha**, com teto de 1.792 bytes. Reserva 256 bytes para o frame interno de 7 bytes e nonce/tag de 48 bytes e margem: o corpo do envelope criptográfico fica estritamente abaixo de 2.048 bytes, comprovado pelo teste da resposta real v3. Headers HTTP conservam seus limites independentes; não se somam ao orçamento de corpo do protocolo. Nenhum limite global de transporte foi ampliado.

`next_cursor=""` significa fim da página final, inclusive histórico vazio. Não há truncamento de campos, salto de item ou cursor avançado além de item entregue. Se o primeiro item restante não couber, a resposta é `ok=false, code=limit_exceeded`; é necessário corrigir o registro por procedimento autorizado antes de continuar. Se um item posterior não couber, a página entrega apenas o prefixo que cabe e devolve o cursor desse prefixo; a consulta seguinte recusa explicitamente o item grande. Nenhum conteúdo/argumento/resultado completo é incluído no resumo.

A leitura é de histórico vivo, não um snapshot durável: remoções entre consultas são omitidas, e remover a linha âncora não invalida o cursor. Inserções com chave mais nova que o cursor ficam para uma nova travessia; inserções retrodatadas ou com relógio recuado abaixo do cursor podem aparecer nas páginas seguintes. Reconsultar o mesmo cursor é uma leitura idempotente, sujeita às alterações atuais, sem efeito de execução. Atualizar tarefas na interface reinicia a travessia; “Carregar mais tarefas” usa somente a operação nova. Respostas atrasadas após reinício da listagem/sessão são descartadas por geração local.

Sem migration ou dependência nova. Os índices existentes permitem restringir `owner`, mas não cobrem a nova ordenação: SQLite pode ordenar o histórico com estrutura temporária. Não se promete custo constante em bases grandes; um índice composto futuro exige medição e migration aditiva, não alteração da 0019 aplicada.

Rust e TypeScript têm decodificadores próprios, estritos para o novo DTO: campos exatos, catálogo/estados fechados, no máximo quatro itens, ordem decrescente, avanço estrito em relação ao cursor solicitado e cursor de continuação vinculado à última linha. Os decodificadores e DTOs da chamada antiga não receberam campos novos. Aplicação v1 e envelope v3 permanecem; runtimes antigos recusam a operação desconhecida sem fallback para uma semântica diferente. A emenda consta do contrato MAC-003; cliente/backend desta candidata precisam ser usados juntos.

Evidências e comandos: [WORKFLOW_HISTORY_PAGINATION_2026-10-14.md](WORKFLOW_HISTORY_PAGINATION_2026-10-14.md). **Smoke visual e P2 de Aprovações continuam pendentes.**
