# R2 — relatório de estabilização de idempotência

**Estado:** candidata para auditoria independente; não é aceite do G5. Sem merge, push, tag, deploy ou conexão com contas reais.
**Data:** 2026-09-26
**Baseline congelado:** `feat/jarvis-unified-r1-2026-09-26` em `b43f40e6c095461e239e6edb7662d560fcd789a0`
**Branch R2:** `feat/jarvis-unified-r2-2026-09-26`
**Worktree R2:** `/Users/vic/.codex/worktrees/jarvis-unified-r2-2026-09-26/Jarvis-Victor-OS`
**Commit de implementação, testes e ADR:** `9b15007be2c4567ecde5d9a8dd19c176ef6eea39`

## Objetivo e decisão

Corrigir a colisão de chaves entre criação e importação com uma chave composta por principal, operação e texto da chave. A coluna `operation` é definida no servidor e protegida por `CHECK`; o cliente continua enviando somente `idempotency_key`.

| Operação persistida | Uso |
|---|---|
| `mission.create` | Criar Missão |
| `mission.transition` | Transições diretas e etapas supervisionadas |
| `mission.import` | Replay do lote importado |
| `mission.import.item` | Registro interno de cada documento importado |
| `mission.review.decide` | Decisão de revisão |
| `mission.review.revise` | Nova versão após ajustes |
| `legacy_unresolved` | Registro anterior à R2 sem proveniência suficiente |

Para a mesma operação e principal, o mesmo corpo continua sendo replay e um corpo diferente responde 409. Texto de chave idêntico em operações novas diferentes não se confunde. A busca sempre respeita o principal.

## Pré-voo e preservação

- Diagnóstico do executor: stdout `executor-stdout-ok`, linha `exit=0`, exit code 0.
- R1 conferida limpa em `b43f40e6c095461e239e6edb7662d560fcd789a0`; `main` continua `8e7c09bb303deb6fe444a3a455961519a5f414d2`, ancestral de R1.
- `a6cd0fffc4207a10462bef853a8994a8fd037c12` não é ancestral de R1 nem foi incorporado à R2.
- R2 é uma worktree nova diretamente de R1. A worktree R1 e o checkout compartilhado permaneceram intactos.
- O checkout compartilhado continua em `feat/gate2.0-e-integracao-web-api`, SHA `e648e92467396ce67b75019858fbcd0ee5557042`. Os quatro arquivos não rastreados foram preservados com os hashes conferidos no pré-voo:

| Arquivo | SHA-256 |
|---|---|
| `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md` | `bf32f4a2328eb6da1a6be59785f6bb129e683cbb684256ce718d0336763ca88f` |
| `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md` | `8d16c2c0d70eb19e9bbbe7d458e9045344ec6a82f3845d7a4defb0262314d149` |
| `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` | `f9b6f9337b8da8eee2b5043ccac321f2ec519980701c66cf7cc0e16fb9132715` |
| `package-lock.json` | `928ea8e3b375c204f6307e85f190ac76074dddea2b79fefcda27fcd4ca61afeb` |

O relatório independente `AUDIT_REPORT_R1.md` estava disponível em `/tmp/jarvis-independent-r1-audit.BVLhVa/` e foi lido. A worktree original R1 estava presente, limpa e permaneceu sem alterações.

## Reprodução e causa raiz

O relatório independente R1 identificou este caso reproduzível:

1. Criar uma Missão usando a chave `audit-import-keyspace:mission_audit_internal_key_collision`.
2. Importar um documento válido com ID `mission_audit_internal_key_collision`, evento novo e chave de lote `audit-import-keyspace`.
3. O import deriva para o documento a mesma chave textual `audit-import-keyspace:mission_audit_internal_key_collision`.

A tabela antiga tinha `PRIMARY KEY (owner, idempotency_key)`. `create()` gravava a chave recebida; `_insert_record()` gravava a chave interna do import na mesma tabela e no mesmo namespace. A unicidade levantava `sqlite3.IntegrityError`; o handler genérico de SQLite em `main.py` respondia 503 `memória local indisponível`. O import já estava dentro de `BEGIN IMMEDIATE`, então a tentativa era revertida, mas o conflito válido era classificado como indisponibilidade. O relatório independente registrou a reversão completa, sem alteração de missões/eventos/chaves, e `PRAGMA integrity_check = ok`.

Reproduzi o mesmo caminho no R2 antes da alteração usando o teste `test_import_internal_key_can_match_a_user_create_key_without_collision`: resposta observada **503**, com o mesmo detalhe público. Após a mudança, o mesmo teste passa com HTTP 200; as duas Missões permanecem e `PRAGMA integrity_check` continua `ok`.

IDs de evento/missão não foram confundidos com essa colisão de chave: os probes R1 de IDs repetidos no lote, quarentena por evento repetido dentro de documento, colisões globais de identidade e isolamento de principal continuam exercitados e passam.

## Migração e semântica de registros legados

A migração `0013_mission_idempotency_scopes.sql` reconstrói a tabela dentro da transação de migração e troca a chave primária para `(owner, operation, idempotency_key)`. Preserva `owner`, chave, `mission_id`, hash do corpo e `result_json` de todas as linhas anteriores. Como o esquema antigo não registrava a operação de origem, cada registro pré-R2 recebe `operation='legacy_unresolved'`; nenhum registro é adivinhado, sobrescrito ou descartado.

Se o mesmo principal tentar usar uma chave que permaneça em `legacy_unresolved`, qualquer operação recebe HTTP 409 com detalhe genérico `chave de idempotência legada exige reconciliação`. Nenhum valor legado é devolvido. Outro principal pode usar o mesmo texto sem cruzar registros. A R2 não reclassifica automaticamente registros antigos: reconciliação manual exige revisar sua proveniência. Esse comportamento está documentado em [ADR 008](../../adr/008-operation-scoped-idempotency.md).

As operações usam leitura explícita do escopo e `INSERT` comum. O código não transforma todo `IntegrityError` em conflito nem usa `INSERT OR IGNORE` para as linhas de idempotência. A constraint da execução supervisionada também só é mapeada a 409 quando a consulta encontra a execução conflitante esperada; outras violações permanecem erros de armazenamento.

Alternativas descartadas: codificar operação como prefixo no texto da chave deixaria colisão possível com chaves arbitrárias do cliente; capturar todo `IntegrityError` como 409 ocultaria falhas de esquema/dados; inferir a operação de linhas antigas por `result_json`, hash ou ID não é confiável para o formato legado.

## Arquivos alterados

- `apps/api/migrations/0013_mission_idempotency_scopes.sql`
- `apps/api/mission_repository.py` e `apps/api/mission_engine.py`
- `apps/api/test_memory_store.py`, `test_mission_import_identity.py`, `test_missions_api.py` e `test_review_api.py`
- `docs/adr/008-operation-scoped-idempotency.md`
- Capturas da verificação visual em `docs/nightly/2026-09-26/r2-captures/`

As provas cobrem a colisão exata, chave igual entre criação/importação/transição/revisão, replay e corpo diferente dentro da mesma operação, isolamento entre principais, IDs repetidos, resposta perdida com reinício, corridas de criação e importação, migração de chave legada, erro de constraint não reclassificado, rollback e integridade. A restauração de backup cifrado também verifica o escopo `mission.import` restaurado.

## Resultados reproduzidos

| Verificação | Resultado |
|---|---|
| `apps/api: uv run --locked pytest -q` | **217 passed**, 2 avisos, exit 0 |
| Probes G4/G5 e identidade (`test_mission_engine.py`, `test_mission_auth_races.py`, `test_review_api.py`, `test_knowledge_api.py`, `test_mission_import_identity.py`) | **50 passed**, 1 aviso, exit 0 |
| Probe da colisão exata após a correção | **1 passed**, HTTP 200, exit 0 (1 aviso de dependência) |
| `apps/web: npm test -- --run` | **66 passed** em 15 arquivos, exit 0 |
| `apps/web: npm run typecheck` | PASS, exit 0 |
| `apps/web: npm run lint` | PASS, exit 0; `next lint` emite aviso de depreciação |
| `apps/web: npm run build` | PASS, exit 0; 11 rotas estáticas |
| E2E completo, rodada 1 (`unset CI; npm run e2e`) | **54 passed, 2 skipped**, exit 0; retries 0 |
| E2E completo, rodada 2 consecutiva (`unset CI; npm run e2e`) | **54 passed, 2 skipped**, exit 0; retries 0 |
| Matriz visual E2E | 80 verificações: 8 rotas × 10 larguras; todas passaram, incluindo 767/768/769 px |
| `git -c core.whitespace=cr-at-eol diff --check` | PASS antes do commit de implementação e na revisão staged da entrega documental |

Os dois skips são mantidos como skips, não como aprovação: `QA visual noturna: dez larguras sem overflow e sobreposição nas telas principais` é ignorado no projeto mobile e executado no desktop; `navegação mobile Mais mantém áreas acessíveis por teclado` é ignorado no desktop e executado no mobile. As duas rodadas completas mostram ambos os casos complementares.

As capturas são da rota `/missoes`, no estado DEMO vazio. A 767 px a navegação inferior aparece; a 768 px começa o rail desktop; a 769 px o rail continua. Não houve alteração de UI. O arquivo R2 de 768 px é byte a byte igual à captura R1 de 768 px.

| Largura | Captura | Dimensão | SHA-256 |
|---|---|---:|---|
| 767 px | [R2_MISSOES_767.png](r2-captures/R2_MISSOES_767.png) | 767 × 989 | `b9f2641b7e6a39a6279cdf154b53b9bf769b4deb0ef4e0a69f39260b9388c8fd` |
| 768 px | [R2_MISSOES_768.png](r2-captures/R2_MISSOES_768.png) | 768 × 900 | `d2556eacce54bf6670a19c82633c4f9320de93753286f16dfbe4072a5bf303b9` |
| 769 px | [R2_MISSOES_769.png](r2-captures/R2_MISSOES_769.png) | 769 × 1034 | `e2eab02313b4244f5e86355522b27599bbaa29ba7aff61c946780870bdc4bce9` |

## Limites e encaminhamento

- A R2 permanece candidata sintética local de processo único; os testes não autorizam multiworker, dados reais, OAuth, fontes externas, deploy ou cliente nativo conectado.
- Registros legados sem proveniência correta ficam deliberadamente bloqueados até reconciliação; não há comando de reclassificação nesta entrega.
- O web continua separando DEMO do SQLite sintético. As jornadas web/API/revisão/contexto de teste usam somente dados locais sintéticos.
- Nenhuma compilação nativa foi iniciada; o bundle macOS existente não precisou de verificação para esta alteração de banco/API.
- Próximo passo: entregar `feat/jarvis-unified-r2-2026-09-26` para auditoria independente. Não iniciar outro gate antes desse parecer.
