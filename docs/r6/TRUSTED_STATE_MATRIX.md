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

## Ponto canônico de código

- `apps/api/source_admission.py`: `resolve_trusted_source_projection` descobre candidatos por relações de artefato, conhecimento e revisão e entrega a prova somente se a cadeia inteira apontar ao mesmo registro.
- `redact_mission_record`, `review_is_unverified_source`, `verified_source_for_knowledge` e `canonical_knowledge_decision` derivam projeções desse verificador; revisões e lista de fontes usam o mesmo resolver.
- `canonical_review_state` valida as decisões de revisão, snapshot e hash. Não declara que o ledger autentica o administrador do próprio banco.
- `mission_api.py`, `selected_source_api.py`, `review_api.py`, `knowledge_api.py` e execução de contexto continuam impondo seus grants existentes.

## Busca estática

| Grupo encontrado | Classificação | Regra de leitura |
|---|---|---|
| `source_admission.py` (`synthetic_verified`, `selected`, `approved`, `quarantined`, `unverified`) | Canonical projection + stored claim comparison | Claims são comparadas ao catálogo/prova; apenas projeção abre conteúdo |
| `selected_source_api.py` | Authorization + canonical projection + display-only | Grant local primeiro; campos publicáveis vêm da prova |
| `mission_repository.py` | Canonical review projection + authorization + writes | Decisão passa pelo ledger; revisão de fixture não aceita conteúdo arbitrário |
| `knowledge_api.py` | Authorization + canonical knowledge projection | Lista, decisão, contexto e skill consultam a prova e a decisão canônicas |
| `memory_store.py`/migrations | Migration + armazenamento | DDL, triggers e normalização preservam dados; não são identidade criptográfica |
| `test_*.py`, `e2e/*.spec.ts` | Testes/probes | Claims aparecem como dados de ataque e asserções, não como prova produtiva |
| UI (`apps/web`) | Display-only | Rótulos visíveis não autorizam leitura ou decisão |

Nenhum endpoint deve usar `classification`, `state`, `review_state`, `approved`, `selection_state` ou uma string importada como prova isolada. A exceção de autenticidade do escritor SQLite está declarada na [ADR-010](../adr/010-local-review-trust-boundary.md).
