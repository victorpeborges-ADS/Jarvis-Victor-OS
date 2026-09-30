# R6.1 — Matriz de adulteração de knowledge

Os casos abaixo usam somente banco SQLite temporário e fixtures sintéticas. A prova é verificada diretamente por `resolve_trusted_knowledge_projection` e pela projeção de `GET /real/knowledge`. O caso 1 também exercita missão, fonte, revisão, decisão, contexto, build-context e conclusão da missão.

| # | Probe (`test_knowledge_provenance.py`) | Adulteração | Resultado exigido |
|---:|---|---|---|
| 1 | `selected_to_skill_without_review_and_bytes` | `selected_original` → `skill_derived`, apaga review, muda conteúdo e move o vínculo da fonte para outra knowledge | Quarentena em todas as superfícies; 409 ao aprovar; zero contexto; nenhum conteúdo em artefato/skill/conclusão |
| 2 | `selected_to_skill_with_review` | Troca kind mantendo `source_review_id` | Quarentena |
| 3 | `derived_to_selected` | `skill_derived` → `selected_original` | Quarentena |
| 4 | `derived_cross_mission` | Move knowledge para outra missão válida | Quarentena |
| 5 | `derived_cross_owner` | Troca owner sem trocar a missão | Sem prova para ambos os owners; linha não aparece na lista do principal anterior |
| 6 | `producer_artifact_missing` | Remove o artefato produtor do documento | Quarentena |
| 7 | `producer_artifact_from_other_mission` | Substitui o artefato pelo de outra missão | Quarentena |
| 8 | `execution_digest_changed` | Adultera `input_digest` da execução | Quarentena |
| 9 | `knowledge_content_changed` | Troca bytes do knowledge | Quarentena, sem hash confiável |
| 10 | `execution_missing` | Remove a execução produtora | Quarentena |
| 11 | `execution_moved_to_other_mission` | Move a execução para outra missão válida | Quarentena |
| 12 | `unknown_kind` | Persiste kind fora da enumeração, simulando banco inconsistente | Quarentena |
| 13 | `null_kind_rejected_by_schema` | Tenta gravar NULL e kind inválido | NULL é rejeitado pelo schema; kind inválido, sob violação deliberada do CHECK, falha fechada |
| 14 | `orphan_knowledge` | Insere knowledge sem execução/artefato/review correspondentes | Quarentena |
| 15 | `selected_relinked_to_other_valid_source` | Religa uma fonte ao knowledge válido de outra fixture | Ambas as relações deixam de fechar; quarentena |
| 16 | `source_relinked_to_derived_knowledge` | Religa selected source a um derivado válido | Origem derivada passa a ter conflito; ambas as projeções falham fechadas |
| 17 | `two_valid_sources_crossed` | Cruza os IDs de knowledge de duas fontes válidas | As duas linhagens falham fechadas |
| 18 | `four_fields_changed_together` | Troca conteúdo, missão, versão e remove o artefato | Quarentena |
| 19 | `approved_state_without_provenance` | Grava estado `approved` e kind inválido sem prova/ledger | Quarentena; estado armazenado não concede aprovação |
| 20 | `decision_ledger_from_other_knowledge` | Insere para outro knowledge uma decisão válida de outra origem | Ledger divergente invalida a projeção; bytes retidos |

O schema proíbe kind nulo e a API nunca o aceita como entrada. A linha 13 prova tanto essa rejeição quanto o comportamento de leitura para valores inválidos persistidos por uma adulteração que ignora o `CHECK`.
