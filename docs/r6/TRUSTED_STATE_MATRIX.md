# R6 — Matriz de claims e projeções confiáveis

| Registro/campo | Categoria | Fonte canônica | Se divergir |
|---|---|---|---|
| `selected_synthetic_sources.owner` | Stored claim | Principal da requisição e proprietário da missão/fonte/conhecimento/revisão | Fonte e conteúdo ficam retidos |
| `mission_id` / `domain_id` da fonte | Stored claim | Missão persistida, documento da missão, conhecimento, revisão e concessão da sessão | Relação cruzada falha fechada |
| `classification`, `state` | Stored claim, nunca prova | Resultado de `resolve_trusted_source_projection` + `prove_source` | API não projeta `synthetic_verified`/`selected` |
| `fixture_id`, catálogo e versão | Stored claim | `FIXTURES`, `CATALOG_ID`, `CATALOG_VERSION` versionados no servidor | Sem fixture/versão exata, reter fonte |
| bytes, tamanho e hashes | Stored claim | Bytes da fixture no catálogo e conteúdo igual em snapshot, artefato e conhecimento | Omitir bytes e hashes confiáveis |
| `provenance_json` | Stored claim | Proveniência imutável da fixture no catálogo | Omitir proveniência |
| `review_id`, `knowledge_id`, `artifact_id` | Stored links | Uma única cadeia owner/mission/domain/artifact/source/knowledge/review | Vínculo órfão ou misto é quarentena |
| `source_refs[].source_id` | Stored link | Deve apontar para a única fonte descoberta pelas relações e para a referência do snapshot | Referência ausente, extra ou diferente retém conteúdo |
| snapshot da revisão | Snapshot de dados, não autenticador humano | JSON canônico, digest, versão, artefato e cópia corrente da missão | Snapshot inválido ou separado do artefato retém revisão/fonte |
| `review_state` no documento da missão | Stored claim | `canonical_artifact_state`/`canonical_review_state` | Claim não é usado como aprovação |
| `mission_review_decisions` | Ledger local | Linha única que coincide com revisão, owner, missão, artefato, versão, hash, decisão, ator, motivo, instante e snapshot | Ausente, antiga, duplicada ou divergente resulta em `pending`/não provado |
| `mission_knowledge_decisions` | Ledger local | Owner, missão, domínio, hash do conteúdo, decisão e origem aprovada | Contexto não inclui conteúdo |
| `selected_original` / `skill_derived` | Classificação persistida | `resolve_trusted_source_projection` também procura relações pela ID do knowledge, sem confiar na claim `kind` | Claim de tipo divergente é quarantined; não aprovar nem montar contexto |
| Sessão e grant | Autorização | Store local volátil e confirmação dentro da ordem de locks existente | Resposta negada/revogação respeitada; prova de fonte não substitui autorização |
| Estado exibido de quarentena | Display-only | Resultado fail-closed da projeção | Placeholders sem conteúdo, hash ou proveniência de confiança |
| Estado de migração/reconciliação | Migration | Fixtures históricas e `legacy_source_fixture` byte-exato | Sem inferência; fonte antiga permanece quarantined |

## Knowledge: origem e capacidades

`mission_knowledge.kind` é uma claim persistida, não evidência de proveniência. A única enumeração admitida pelo schema atual é `selected_original` e `skill_derived`; o campo é `NOT NULL` e tem `CHECK`. `origin` e `source_type` não existem nessa tabela. O `state` armazenado historicamente admite `staged` e `review`; a API calcula o estado público a partir da prova e de `mission_knowledge_decisions`, usando também `quarantined` quando a prova falha. Os valores `approved` e `rejected` vêm do ledger, não do campo armazenado.

| Stored claim (`kind`) | Evidência canônica positiva | Projeção pública | Expor bytes? | Aprovar? | Contexto? | Alimentar skill? |
|---|---|---|---:|---:|---:|---:|
| `selected_original` | Uma cadeia única e coincidente: owner → missão/documento → domínio → artefato e referência → selected source → catálogo/versão → bytes e SHA-256 da fixture → knowledge e conteúdo → revisão, snapshot e decisão canônica quando existente. `resolve_trusted_source_projection`/`prove_source` validam os vínculos. | `origin_type=selected_original`, `origin_verified=true`, `classification=synthetic_verified`; divergência produz `quarantined`, `unverified`, sem conteúdo nem SHA confiável. | Sim, apenas depois da prova positiva; a aprovação do artefato não aprova o knowledge. | Sim, depois de revisão do artefato aprovada e prova atual válida. | Apenas com revisão do artefato e decisão do knowledge aprovadas, hashes atuais e concessão de leitura. | Sim, exclusivamente pelo contexto aprovado acima. |
| `skill_derived` | Missão/documento e owner/domain; tarefa única `task_capture` concluída; execução `committed` de `capture-and-classify@1.0.0` com tentativa e input digest determinísticos; knowledge ID e bytes reproduzidos pelo produtor; artefato determinístico e snapshot/revisão da versão 1; eventos de conclusão e criação correlacionados na missão e em `mission_events`. Não pode existir elo de selected source conflitante. | `origin_type=skill_derived`, `origin_verified=true`, `classification=synthetic_verified`; prova incompleta, origem ambígua ou claim divergente produz `quarantined`, `unverified`, sem conteúdo nem SHA confiável. | Sim, depois da prova positiva, inclusive enquanto aguarda a revisão humana sintética; bytes permanecem retidos se a prova deixar de fechar. | Sim, somente com revisão do artefato aprovada e prova atual válida. | Apenas com revisão do artefato e decisão do knowledge aprovadas, hashes atuais e concessão de leitura. | Sim, exclusivamente pelo contexto aprovado acima. |
| Qualquer kind desconhecido/inválido ou knowledge órfão | Nenhuma prova suportada; não há inferência de tipo pela ausência de vínculo com selected source. | `quarantined`, `origin_verified=false`, `origin_type=null`, `content_withheld=true`. | Não. | Não. | Não. | Não. |

O endpoint não fornece detalhe individual de knowledge; `GET /real/knowledge` é a superfície de listagem. O conteúdo do contexto é criado apenas por `assemble_context`, que exige prova da origem, decisão canônica aprovada e revisão atual aprovada. A UI consome os campos da projeção da API e nunca promove `kind` localmente.

## Ponto canônico de código

- `apps/api/source_admission.py`: `resolve_trusted_source_projection` descobre candidatos por relações de artefato, conhecimento e revisão e entrega a prova somente se a cadeia inteira apontar ao mesmo registro. `resolve_trusted_knowledge_projection` despacha explicitamente para prova positiva de cada origem suportada e falha fechada para qualquer claim sem prova.
- `redact_mission_record`, `review_is_unverified_source`, `verified_source_for_knowledge` e `canonical_knowledge_decision` derivam projeções desse verificador; revisões e lista de fontes usam o mesmo resolver.
- `canonical_review_state` valida as decisões de revisão, snapshot e hash. Não declara que o ledger autentica o administrador do próprio banco.
- `mission_api.py`, `selected_source_api.py`, `review_api.py`, `knowledge_api.py` e execução de contexto continuam impondo seus grants existentes.

## Busca estática

| Grupo encontrado | Classificação | Regra de leitura |
|---|---|---|
| `source_admission.py` (`skill_derived`, `selected_original`, `synthetic_verified`, `selected`, `approved`, `quarantined`, `unverified`) | Stored claim + canonical evidence + projection | Cada tipo exige sua prova explícita; kind sem prova resulta em quarentena |
| `selected_source_api.py` | Authorization + canonical projection + display-only | Grant local primeiro; campos publicáveis vêm da prova |
| `mission_repository.py` | Canonical review projection + authorization + writes | Decisão passa pelo ledger; revisão de fixture não aceita conteúdo arbitrário |
| `knowledge_api.py` | Authorization + canonical knowledge projection + capability projection | Lista e decisão consultam a prova positiva; contexto/skill também exige aprovação do artefato e do knowledge |
| `memory_store.py`/migrations | Migration + armazenamento | DDL, triggers e normalização preservam dados; não são identidade criptográfica |
| `test_*.py`, `e2e/*.spec.ts` | Testes/probes | Claims aparecem como dados de ataque e asserções, não como prova produtiva |
| UI (`apps/web`) | Display-only | Rótulo de origem é escolhido apenas por `origin_verified` retornado pela API; unverified aparece como “Origem não verificada” e bytes retidos |

Nenhum endpoint deve usar `classification`, `state`, `review_state`, `approved`, `selection_state` ou uma string importada como prova isolada. A exceção de autenticidade do escritor SQLite está declarada na [ADR-010](../adr/010-local-review-trust-boundary.md).
