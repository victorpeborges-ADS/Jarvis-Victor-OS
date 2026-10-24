# Contrato dos conectores em fixture — 17/10/2026

Subentrega da frente 6, só na candidata. Não conecta conta, não inicia OAuth e não abre rede. O calendário simulado do Gate D permanece o contrato já aceito. Este adaptador não o substitui e não grava o banco dele.

## Contrato

Gmail, Calendar, Drive, GitHub e MCP usam o mesmo resultado: origem sintética, identidade do conector, horário de coleta, regra de revogação e frescor, e os limites abaixo. O schema é fechado. Campo extra, schema ausente ou tipo errado recusa a leitura inteira.

Limites desta etapa: 20 itens, 2048 bytes e 1000 ms. DNS fica em `do_not_resolve`, redirect em `refuse` e egress em `disabled`. URL local, loopback, link-local, metadata, nome que precisaria de DNS, IP público e redirect são recusados por classificação do texto. Não há resolução de nome nem abertura de conexão.

Escopo mínimo declarado, e não concedido: `gmail.readonly`, `calendar.readonly`, `drive.metadata.readonly`, `metadata:read`, `tools.list.readonly`. Evento de dia inteiro continua sem contrato e a fixture que o marca é recusada.

Conteúdo externo é dado não confiável. Não concede permissão, não altera instrução e não abre ferramenta. Anotação remota de MCP não entra na allowlist. A allowlist local desta etapa só reconhece `fixture.echo` como catálogo, sem executar.

A busca unificada marca fonte velha, revogada ou recusada e não coloca o texto dela entre os itens atuais. Se alguma fonte não está atual, o resultado da busca vem com `complete` falso. Duplicata no mesmo conector e na mesma identidade externa colapsa numa cópia.

O relógio de frescor é do adaptador: 900 segundos, e 300 para MCP. A fixture não aumenta esse prazo. Revogação vale pelo flag da fixture ou por um registro local volátil. Os dois tiram a fonte do resultado atual.

## O que o falso prova

Prova, sem rede e sem banco, que a leitura sintética chega a um resultado fechado para os cinco conectores. Também prova recusa de resposta malformada, fonte revogada, timeout sem espera, redirect sem seguir o destino, URL local e os outros alvos acima, duplicata e resultado grande. A projeção do calendário simulado lê a memória do Gate D e devolve o mesmo formato, com conta sintética.

## O que o falso não prova

Não prova conta, OAuth, token, consentimento, custo, egress real, DNS real, paginação de API, sync incremental, evento de dia inteiro, processo MCP ou revogação no provedor. Um teste verde não é conexão. O descriptor antigo de Gmail e Calendar continua desconectado. Este módulo não o chama.

## Aprovações que faltam

Cada passo está BLOCKED e não iniciado. `begin_real_connector` não muda esse estado.

| Conector | Conta | OAuth | Escopo | Dado permitido | Custo | Egress |
|---|---|---|---|---|---|---|
| Gmail | não escolhida | não iniciado | `gmail.readonly` não concedido | não decidido | não autorizado | não autorizado |
| Calendar | não escolhida; o simulador não é conta | não iniciado | `calendar.readonly` não concedido; dia inteiro sem contrato | não decidido | não autorizado | não autorizado |
| Drive | não escolhida | não iniciado | `drive.metadata.readonly` não concedido | não decidido | não autorizado | não autorizado |
| GitHub | não escolhida | não iniciado | leitura de metadado não concedida | não decidido | não autorizado | não autorizado |
| MCP | servidor não escolhido; stdio seria instalação à parte | não iniciado | allowlist real não aprovada | não decidido | não autorizado | não autorizado |

O roadmap do checkout compartilhado mudou durante esta etapa. A linha da frente 6 desse arquivo não foi editada. O estado fica neste documento.
