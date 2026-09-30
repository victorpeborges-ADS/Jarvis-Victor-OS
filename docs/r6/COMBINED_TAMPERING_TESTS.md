# R6 — Probes de adulteração combinatória

Implementados em `apps/api/test_r6_combined_tampering.py`. Cada caso parte de uma fonte sintética válida com as duas decisões locais, aplica uma combinação inconsistente e verifica as superfícies de leitura, decisão, contexto, execução da skill `build-context` e conclusão da missão.

As asserções comuns exigem: conteúdo e metadados confiáveis retidos no GET de missão; ausência de fonte `synthetic_verified` no GET de fontes; revisão pendente/não provada com artefato e histórico retidos (ou 404 no caso de revisão apagada); knowledge sem conteúdo/hash confiável; decisão de knowledge/review recusada; contexto sem itens incluídos; três etapas determinísticas concluem a missão sem ecoar bytes da fixture.

| # | Combinação adversarial | Resultado coberto |
|---:|---|---|
| 1 | `artifact.source_id` trocado + `source.owner` trocado (caso exato da auditoria R5) | Retém a missão apesar de a referência alterada não localizar a fonte |
| 2 | Owner incorreto + `mission_id` de outra missão existente | A existência isolada da outra missão não fecha a cadeia |
| 3 | `source.mission_id` trocado + `artifact.source_id` alterado | Snapshot/relação original identifica a cadeia quebrada |
| 4 | Domínio incorreto + referência do artefato alterada | O domínio da missão e da fixture não coincide |
| 5 | `knowledge.source_review_id` cruzado + fonte/artefato ainda válidos isoladamente | O knowledge não pode combinar revisão alheia |
| 6 | `review.artifact_id` trocado + snapshot re-hashado para esse ID | Snapshot internamente coerente ainda diverge da missão/fonte |
| 7 | `fixture_id` falso + hashes novamente calculados sobre bytes válidos | O catálogo servidor não encontra a identidade alegada |
| 8 | `catalog_version` adulterada + bytes originais válidos | Versão exata do catálogo é obrigatória |
| 9 | Snapshot copiado de uma segunda fonte sintética válida | Referência e snapshot selecionam duas identidades; reprova |
| 10 | Owner A/B cruzado | Principal da chamada não coincide com owner/mission |
| 11 | Missão A/B e source B cruzados | Duas fontes aparecem na mesma relação observada; reprova |
| 12 | Duas fontes válidas individualmente, com artefato A apontando para B | Não combina prova válida de A com referência válida de B |
| 13 | Fonte com `review_id` órfão | A fonte não reconstrói a revisão |
| 14 | Knowledge órfão por remoção da linha ligada | Fonte/artefato sem linha de conhecimento não é confiável |
| 15 | Review órfã por remoção da linha de revisão | Fonte é retida; endpoint da revisão devolve 404 |
| 16 | Snapshot nulo | Snapshot ausente é inválido |
| 17 | Fonte válida + ledger duplicado ligado a outro artefato | Uma decisão extra torna o ledger ambíguo e inválido |
| 18 | Fonte válida + ledger duplicado ligado a outra missão | A identidade lógica do ledger diverge; falha fechada |
| 19 | `knowledge.kind` trocado para `skill_derived`, `source.knowledge_id` órfão e `knowledge.source_review_id` cruzado | Relação pela decisão e pelos bytes do mesmo domínio ainda identifica a fonte; claims alteradas não liberam conteúdo |

## Limite demonstrado

`test_coherent_sqlite_admin_fabrication_is_documented_outside_g5_authenticity` insere um ledger `approved` com todos os campos coerentes com uma revisão pendente. O teste passa ao demonstrar que a projeção aceita essa fabricação quando todos os dados dentro do SQLite são coerentes. O caso é deliberadamente classificado **fora** da garantia de autenticidade do G5: o escritor controla os dados e o registro que seria usado como evidência. Não é uma falha mascarada nem uma promessa de resistência ao administrador.

## Lock/reconcile

Os probes `test_read_and_reconcile_lock_orders_complete_without_deadlock` em `test_r5_trusted_state.py` exercitam `read → reconcile` e `reconcile → read`. A R6 mudou o ponto de pausa da leitura para o resolver canônico; não alterou a ordem dos locks nem adicionou migração.
