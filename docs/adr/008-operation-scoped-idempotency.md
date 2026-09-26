# ADR 008 — chaves de idempotência por operação

- Estado: proposto para candidata R2 local sintética; aguarda auditoria independente.
- Data: 2026-09-26.

## Contexto

`mission_idempotency` era única por `(owner, idempotency_key)`, embora criação, transição, importação e revisão compartilhassem essa tabela. A importação também grava uma chave interna por documento derivada de `chave_do_lote:mission_id`. Uma chave válida escolhida pelo cliente podia, portanto, ocupar essa chave interna e transformar uma colisão de operação em 503.

## Decisão

Cada registro passa a ser identificado estruturalmente por `(owner, operation, idempotency_key)`. O campo `operation` é escolhido pelo servidor e não faz parte de nenhum contrato de entrada:

| Operação | Escopo |
|---|---|
| `mission.create` | criação de missão |
| `mission.transition` | transições diretas e execuções supervisionadas |
| `mission.import` | replay do lote de importação |
| `mission.import.item` | registro interno por documento importado |
| `mission.review.decide` | decisão de revisão |
| `mission.review.revise` | nova versão de artefato após ajustes |

Mesmo principal, mesma operação e mesma chave mantêm as regras existentes: mesmo corpo reproduz o resultado persistido; corpo diferente responde 409. Operações distintas podem usar o mesmo texto de chave sem se confundir. A chave continua isolada pelo principal.

## Migração e registros anteriores

A migração 0013 reconstrói `mission_idempotency` dentro da transação de migração, preserva `owner`, chave, `mission_id`, hash do corpo e `result_json`, e atribui `operation='legacy_unresolved'` a todas as linhas anteriores. A versão antiga não guardava proveniência suficiente para inferir com segurança se uma linha era criação, lote, documento importado, transição ou revisão; nenhum caso é adivinhado.

Um pedido do mesmo principal que apresentar uma chave ainda `legacy_unresolved` recebe 409 com detalhe genérico e sem expor os valores guardados. A linha não é substituída nem reproduzida. A reconciliação de uma linha legada precisa ser feita após revisar a proveniência; a R2 não fornece migração automática nem ferramenta de reclassificação. Outro principal continua isolado e pode usar a mesma chave.

## Integridade e limites

As consultas e inserções de idempotência ocorrem dentro das transações SQLite existentes. As gravações usam `INSERT` comum; colisões esperadas são decididas pelo escopo e por consultas explícitas, sem `INSERT OR IGNORE` ou conversão indiscriminada de `IntegrityError`. Conflitos de identidade de missão/evento continuam 409, lote estruturalmente inválido continua 422 ou quarentena conforme ADRs anteriores, e falhas reais de SQLite continuam falhas de armazenamento.

`mission_review_decisions` conserva sua chave textual no histórico especializado de decisões; por desenho, todas as linhas desse ledger são `mission.review.decide`, e a identidade/replay autoritativa fica na tabela escopada. `selected_synthetic_sources` também permanece em tabela e escopo próprios.

A decisão cobre SQLite sintético de processo único. Não amplia a garantia para vários workers/processos nem autoriza fontes externas ou contas reais. O aceite depende de auditoria independente e das provas de migração, replay, concorrência, restauração de backup e integridade.
