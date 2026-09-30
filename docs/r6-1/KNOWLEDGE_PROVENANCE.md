# R6.1 — Modelo canônico de proveniência de knowledge

## Inventário do schema e das superfícies

`mission_knowledge.kind` é adicionado pela migração `0012_selected_synthetic_sources.sql`. O `CHECK` admite somente `skill_derived` e `selected_original`; a coluna é `NOT NULL`. Não há colunas `origin` ou `source_type` em `mission_knowledge`. `mission_knowledge.state` é armazenado como `staged` ou `review` no schema legado. O estado de aprovação é projetado a partir do ledger `mission_knowledge_decisions`, que admite `approved` ou `rejected`. A API projeta ainda `quarantined` quando não consegue provar a origem/decisão. `GET /real/knowledge` é a única superfície de listagem/detalhe; não existe rota individual de detalhe.

Há dois criadores legítimos no fluxo atual:

1. `MissionEngine` executa a tarefa `task_capture` e chama `synthetic_skill.capture_and_classify`. O fluxo salva `mission_knowledge`, `mission_executions`, o artefato na missão, seu snapshot/revisão e os eventos correlacionados.
2. `POST /real/missions/{id}/sources` admite uma fixture do catálogo versionado e cria a revisão, o artefato, `selected_synthetic_sources` e seu registro `mission_knowledge`.

Importação de missões não cria knowledge. Nenhuma origem adicional é presumida pelo fato de um registro não se relacionar a uma selected source.

## Prova de cada origem

| Origem alegada | Quem/fluxo | Evidência e versão | Coincidências obrigatórias | Revisão/capacidades |
|---|---|---|---|---|
| `selected_original` | Sessão local autorizada, via endpoint de seleção de fonte sintética | Fixture presente em `FIXTURES`, `CATALOG_ID` e `CATALOG_VERSION`; bytes e SHA-256; artefato e snapshot; review da versão selecionada; vínculo de `selected_synthetic_sources` | Mesmo owner, missão e domínio no principal, missão/documento, artefato, selected source, catálogo, knowledge, revisão e snapshot; bytes/hash correspondentes | A API pode exibir bytes após prova, inclusive antes da decisão. Aprovação do knowledge exige review aprovado. Contexto e uso por skill exigem review e knowledge aprovados e hashes atuais. |
| `skill_derived` | `MissionEngine` → tarefa `task_capture` → `capture-and-classify@1.0.0` | Execução committed com identidade determinística, attempt e input digest; knowledge ID/conteúdo reproduzidos pelo produtor; artefato determinístico, SHA/snapshot e revisão de versão 1; eventos `task_completed` e `artifact_created` com chave estável e presença correspondente em missão e `mission_events` | Owner, mission e domain do registro, documento, execução, eventos, artefato e review; skill/version/digest/data e payload iguais à reprodução local do skill | Prova positiva permite exibição staged. Aprovação depende da review aprovada. Contexto e uso por skill dependem também da decisão do knowledge aprovada. |
| Kind desconhecido, inválido, nulo, legado sem vínculos ou prova incompleta | Não existe fluxo suportado | Nenhuma; claim isolada, links ausentes ou divergentes não são fallback | Qualquer elo sem coincidência invalida a projeção | Conteúdo e hash retidos; não aprovar, incluir em contexto nem alimentar skill. |

## Regra de decisão

`resolve_trusted_knowledge_projection(connection, knowledge, owner)` despacha apenas para as provas explícitas `selected_original` e `skill_derived`. O tipo persistido escolhe a prova que será tentada; nunca concede confiança. Para `skill_derived`, o código reconstrói a identidade, o input digest e a saída de `capture_and_classify`, confere a execução committed, o artefato e a review/snapshot, e compara os dois eventos estáveis nas cópias da missão e da tabela `mission_events`. Relação de selected source presente é conflito e invalida essa origem.

O caminho `selected_original` mantém integralmente `resolve_trusted_source_projection` e `prove_source`: owner → missão → domínio → artefato/referências → selected source → catálogo/versão → bytes/hash → knowledge → review/snapshot → ledger de decisão quando aplicável. `canonical_knowledge_decision` só interpreta o ledger depois da prova de origem. `assemble_context` e o executor da skill consultam a mesma projeção e exigem as duas aprovações.

Não foi necessária migração. A prova derivada usa registros que o fluxo atual já persistia. Linhas legadas sem esses registros continuam armazenadas para auditoria e falham fechadas; não há tentativa de inferir sua origem.

## Exposição de API e interface

Quando a prova fecha, a listagem projeta `origin_verified=true`, `origin_type`, `classification=synthetic_verified` e o hash calculado do conteúdo. A capacidade `can_approve` só fica ativa quando a review da origem está aprovada. Quando a prova falha, a API remove conteúdo e hash, limpa os links exibidos, retorna `quarantined`, `origin_verified=false`, `origin_type=null`, `classification=unverified` e desativa aprovação, contexto e uso por skill.

A interface escolhe rótulos só com `origin_verified` e `origin_type` da API. Sem confirmação positiva, mostra “Origem não verificada” e “Conteúdo retido”. O valor de `kind` nunca seleciona um rótulo de origem confiável.

## Busca estática e classificação

Busca feita sobre código produtivo de API/web para `skill_derived`, `selected_original`, `knowledge`, `knowledge_state`, `kind`, `content_withheld`, `synthetic_verified`, `quarantined`, `unverified` e `assemble_context`; arquivos de teste foram revisados separadamente.

| Local/ocorrência | Classe | Leitura verificada |
|---|---|---|
| `source_admission.py`: comparações `kind == selected_original`/`skill_derived` | Claim → canonical evidence | Escolhem uma prova explícita; o branch selecionado exige a cadeia source completa e o branch derivado exige execução/artefato/review/eventos. Kind desconhecido cai em `trusted=false`. |
| `source_admission.py`: `source_projection.applicable` no verificador derivado | Canonical evidence | Uma relação selecionada conflitante falha fechada; `applicable=false` apenas deixa o código tentar a prova derivada completa e não aprova por si só. |
| `resolve_trusted_knowledge_projection` e `canonical_knowledge_decision` | Canonical projection | Origem primeiro; ledger validado depois. Sem origem positiva, retorna `quarantined`. |
| `knowledge_api.py`: filtros de concessão e confirmação | Authorization | Leitura/decisão continua confirmando grants locais dentro da ordem de locks anterior. |
| `knowledge_api.py`: lista, `can_approve`, `assemble_context` e `_source_content_matches` | Projection + capability + authorization | Conteúdo só é retornado após origem/decisão válidas. `assemble_context` verifica origem e as duas aprovações; `_source_content_matches` enumera origens conhecidas e retorna falso para desconhecidas. A comparação de kind na razão de omissão só escolhe o texto de diagnóstico. |
| `selected_source_api.py`, `mission_repository.py`, `review_api.py` | Authorization + canonical projection + display | Proveniência e bytes das fontes/revisões continuam no verificador relacional R6; falhas projetam placeholders sem hash/conteúdo. |
| `mission_engine.py` | Canonical evidence consumer | O executor chama `assemble_context` antes de montar artifact de contexto/skill. |
| `migrations/0012_selected_synthetic_sources.sql` | Migration/schema claim | Enumeração de kinds e link opcional de review; não são prova. Nenhuma migração R6.1 foi criada. |
| `apps/web/lib/knowledge-origin.ts`, `MissionApiPanel.tsx` | Display/capability | Labels e botão usam `origin_verified`, `origin_type` e `can_approve` projetados pela API; conteúdo retido usa placeholder. |
| `mission-core.ts`, `skill-catalog.ts`, `knowledge-context.ts` | DEMO local / test-adjacent | Tipos locais do produto DEMO/browser storage; não são a tabela `mission_knowledge` nem autoridade da API sintética. |
| `test_knowledge_provenance.py`, testes R5/R6 e `audit-g5-review-ui.spec.ts` | Testes/probes | Claims inválidas são valores de entrada adversarial; asserts checam quarentena/retensão e não as usam como prova. |

Não restou ramo de produção “não é selected → aceitar como derived”. A busca encontrou uma checagem auxiliar anterior com esse formato em `_source_content_matches`; ela foi substituída por verificação explícita da projeção positiva e do mesmo `source_review` antes da comparação de bytes.
