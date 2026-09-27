# Modelo de ameaças local — candidata R4

**Escopo:** API FastAPI local, interface web e banco SQLite sintético. Esta revisão cobre admissão, revisão e uso de fontes no Gate 2.0; não amplia a fronteira de confiança para serviços externos.

## Ativos e limites de confiança

- A identidade, o conteúdo e a proveniência do catálogo curado ficam no código versionado do servidor. O navegador envia somente `fixture_id` e uma chave de idempotência.
- Sessões e concessões continuam voláteis, em memória e coordenadas por locks de processo. A API exige origem loopback, sessão local, CSRF e a concessão de domínio apropriada.
- SQLite fica fora do repositório, com WAL e permissões privadas. Revisões usam snapshots persistidos; conhecimento continua `staged` até uma decisão humana própria.
- A fonte de autoridade para uma admissão é o catálogo `jarvis.synthetic_sources` versão `1.0.0`, não campos fornecidos pelo navegador.

O modelo considera um cliente web adulterado ou uma chamada local feita por alguém sem concessão. Considera o usuário local e o código do servidor confiáveis. Um processo com acesso de escrita ao código ou ao arquivo SQLite pode alterar o catálogo, o banco ou ambos; R4 não fornece proteção criptográfica contra o proprietário do processo nem criptografia de dados em repouso.

## Admissão e prova

`GET /real/missions/source-catalog/fixtures` publica IDs, nomes, hashes, classificação e proveniência, sem publicar o texto. `POST /real/missions/{mission_id}/sources` aceita somente o ID de uma fixture curada e a chave de idempotência. Campos extras — conteúdo, nome, hash, confirmação e classificação — são recusados pelo contrato estrito. IDs desconhecidos recebem uma resposta genérica; erros e logs não incluem o texto da requisição.

O servidor usa os bytes do catálogo e confere o hash declarado no próprio catálogo ao iniciar o módulo. A escrita do artefato, snapshot de revisão, conhecimento staged e registro da fonte acontece na mesma transação. Uma falha em qualquer inserção reverte todas as gravações.

Antes de listar conhecimento, decidir conhecimento, montar contexto ou expor uma revisão, o servidor verifica a ligação entre registro da fonte, fixture, conteúdo, hash e snapshot imutável. Conteúdo sem essa prova aparece retido ou em quarentena, não pode receber aprovação de conhecimento e é omitido do contexto. Revisões de fixture não podem substituir os bytes canônicos.

## Registros anteriores e limites de classificação

A migração `0014_curated_source_admission.sql` preserva os registros e converte todos os itens antigos em `unverified` / `quarantined`. No início do serviço, a reconciliação promove somente uma correspondência byte a byte com uma fixture autorizada e snapshot íntegro ligado ao mesmo ID de fonte. Ela não cria nem altera decisões humanas. Registros que não provam essa ligação permanecem em quarentena.

O mecanismo reconhece a origem dos textos que já constam no catálogo. Ele não detecta perfeitamente dados pessoais em texto arbitrário. R4 recusa texto arbitrário na admissão de fonte, mas uma futura ampliação do catálogo ainda exige revisão humana dos novos conteúdos antes da publicação.

## Auditoria dos caminhos de entrada

| Caminho | Tratamento R4 |
| --- | --- |
| Seleção de fontes em `/real/missions/{id}/sources` | Recebe apenas ID de fixture do catálogo. Sem envio de arquivo pelo navegador. |
| Importação em `/real/missions/import` | Importa documentos `Mission` sob confirmação explícita e valida identidade/contrato. Não escreve em `selected_synthetic_sources` nem cria `mission_knowledge`; portanto não classifica o conteúdo como fonte verificada nem o disponibiliza ao montador de contexto ou às skills. Conteúdo importado continua sendo parte do documento da missão local, protegido pelo escopo de missão. |
| Revisão e revisão de versões | A revisão de uma fixture selecionada não pode alterar o conteúdo canônico. Revisões de artefatos comuns não criam conhecimento; nenhuma skill consome texto diretamente de artefatos. |
| Inbox e captura rápida do navegador | Permanecem em armazenamento local/DEMO; não são um endpoint de ingestão da API sintética. |
| Calendar simulado | Usa eventos do simulador e IDs de recursos do servidor; não admite documento enviado pelo usuário. |
| Backup e restauração locais | Preservam o estado e os metadados de quarentena; não classificam, aprovam nem montam contexto durante a restauração. |

A importação explícita de um documento de missão continua sendo um canal de armazenamento local de documentos, distinto da admissão de fontes. O contrato R4 não transforma esses documentos em fontes e não os promove ao contexto. A interface de seleção de fontes desconhecidas foi removida; ela não envia esses arquivos para a API.

## Revogação e implantação

Leituras fazem a checagem de sessão/concessão antes da consulta e montam o snapshot sob o lock de leitura, preservando a ordem estabelecida entre lock de autorização e transação SQLite. Os probes R4 exercitam seis rotas em ambas as ordens: leitura linearizada primeiro e revogação primeiro.

Sessões e concessões são locais e voláteis. Os locks coordenam somente um processo; não se habilitam múltiplos workers, API pública, OAuth, dados reais, contas externas ou serviços persistentes. A janela documentada para uma leitura já linearizada continua válida: a resposta pode ser entregue depois que uma revogação concorrente iniciou, pois a revogação espera o snapshot protegido terminar.

G5 permanece candidato para revisão independente. Esta documentação e os testes R4 não constituem aceite formal de G5.
