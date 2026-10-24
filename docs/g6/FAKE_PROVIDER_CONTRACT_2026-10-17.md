# Contrato do provider falso — 17/10/2026

Subentrega da frente de conversa. Não há rota nova, provider real, dependência nova nem migration.

## O que está no processo

`apps/api/conversation_gateway.py` define o contrato e o único adapter deste passo, `FakeProvider`. O gateway só corre com a sessão local já aberta (`native_session_confirmed`, principal `owner`). O provider recebe o texto do turno e não recebe o token da sessão.

O orçamento de um turno é explícito: tempo, tokens, tentativas, chamadas e repetições idênticas. Estourar um desses limites encerra o turno com um estado terminal e sem publicar o texto. Custo que não veio como número medido fica `unmeasured`. Esse valor não é gravado como zero.

Trocar a conversa ou encerrar a sessão aumenta a geração e apaga o texto visível. Uma resposta que termina depois disso não entra na conversa atual. O cancelamento é cooperativo: o provider observa o evento, e o gateway também descarta o corpo se o evento já estiver ligado na hora de publicar.

O corpo que seria publicado usa o mesmo teto da API, 2048 bytes. Acima disso o estado é `response_too_large` e o texto não fica visível. O id de conversa deste gateway continua volátil. A decisão DEC-14, que nesta data ainda estava aberta, ficou resolvida depois: o snapshot cifrado guarda só o identificador opaco e metadados mínimos, e reabrir esse ID não restaura sessão nem grants.

## O que o falso prova

Prova, em banco nenhum e sem rede, que o gateway chega a um único estado terminal para: resposta repetível, falha com e sem nova tentativa, timeout, tempo esgotado antes de outra chamada, limite de contexto declarado ou sinalizado pelo adapter, tokens de saída acima do orçamento, loop idêntico, limite de chamadas, cancelamento no meio da chamada, resposta atrasada depois de trocar a conversa, resposta atrasada depois de encerrar a sessão, campo extra, corpo acima de 2048 bytes e custo ilegível.

Dois turnos iguais devolvem o mesmo texto, o mesmo custo e o mesmo provider. A geração muda, porque cada turno novo substitui o anterior.

## O que o falso não prova

Não prova qualidade de inteligência. O texto é o script do teste, não uma conclusão de modelo. Não mede se a frase é verdadeira, útil, segura ou sustentada por uma fonte. Não mede tokenizer, latência de rede, custo em dinheiro nem comportamento de um provider real. Um teste verde aqui não é avaliação de modelo.

A leitura lexical em `apps/api/grounded_read.py` usa este gateway só para publicar um recorte que já estava na fonte. Isso continua sem provar inteligência. Streaming e provider real continuam por fazer. O provider real permanece bloqueado até autorização explícita. A frase desta data que deixava ferramenta e artefato por fazer foi superada: o loop de leitura e o artefato sintético já existem, e em 23/10/2026 a rota autenticada citou fato confirmado sem tratar o texto recuperado como instrução.
