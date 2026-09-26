# Autoauditoria separada do G5 congelado

**Objeto:** `4931c56d107f49e01d677c097ef33ceb5618015f`, branch `feat/jarvis-g5-aprovacao-persistente`. Clone destacado temporário: `/tmp/jarvis-g5-audit.a1koN0`. A worktree candidata permaneceu intocada. **Veredito do commit congelado: FAIL. Auditoria independente formal: PENDENTE. Aceite do proprietário: PENDENTE.** Este relatório é uma revisão própria em clone separado. Um segundo agente realizou revisão estática somente leitura depois deste relatório, registrada em `G5_SECOND_REVIEW.md`; não executou provas dinâmicas próprias.

## Baseline comprovado

- `main`: `8e7c09bb303deb6fe444a3a455961519a5f414d2`; candidata descendente, árvore limpa; manutenção `a6cd0ff` fora da linhagem.
- API: `uv sync --locked --python 3.12` e `uv run --locked pytest -q`: **178 passed**, 2 avisos.
- Web: `npm ci` (0 vulnerabilidades reportadas), `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`: **66 testes e demais comandos PASS**.
- E2E oficial: `npm run e2e` duas vezes no clone, **42/42** em cada rodada, desktop/mobile, `CI` ausente e `retries=0`.
- Probes próprios com TestClient e SQLite temporário, além de processo API exclusivo em `127.0.0.1` para SIGKILL; nenhum banco padrão ou conta externa.

## Matriz adversarial do commit congelado

| Cenário | Resultado | Evidência resumida |
|---|---|---|
| Concessão de revisão revogada ou expirada antes do commit | PASS | 403, revisão pendente, zero ledger/eventos. |
| Sessão encerrada durante pausa antes do commit | **FAIL** | logout 204, decisão 200 e estado aprovado. |
| Concessão de escrita revogada após pré-checagem e antes de revisar conteúdo | **FAIL** | revogação 200, revisão v2 criada com 200. |
| Decisões incompatíveis simultâneas | PASS | 200/409, apenas uma entrada no ledger. |
| Replay idêntico / corpo alterado / missão / versão / principal | PASS | replay 200; conflitos 409; principal alheio 404. |
| Snapshot adulterado, motivo vazio, corpo forjado, missão cancelada | PASS | 409/422 conforme o caso; zero decisão indevida. |
| Versão v1 depois de gerar v2 | **FAIL** | GET v1 mostrou conteúdo v2 com SHA v1. |
| Hash do snapshot gravado na decisão | **FAIL** | `artifact_sha256` diferia do SHA-256 canônico de `snapshot_json`. |
| Ledger imutável no banco | **FAIL** | UPDATE SQL direto de `decision_reason` aceito; FKs permitiam CASCADE. |
| Paginação com domínio sem autorização | **FAIL** | filtro após LIMIT devolveu página vazia e cursor de ID oculto. |
| Ponteiro de revisão corrompido em mutation | **FAIL** | 500 sem tratamento de `MissionCorrupt`. |
| Rollback forçado na inserção do ledger | PASS | 503, transação revertida, estado pendente e zero ledger. |
| SIGKILL antes/depois do commit | PASS | antes: pendente/zero ledger; depois: aprovado/uma decisão após reinício. |
| Backup cifrado e restauração isolada | PASS | versões e decisões preservadas; hash errado também era preservado. |
| Sem promoção automática do conhecimento derivado | PASS | `mission_knowledge` permaneceu `staged`; etapas concluídas não foram reexecutadas por aprovação. |
| Origin externo, grant Calendar isolado, CSRF e campos extras | PASS | 403/422 conforme o caso. Host específico não recebeu probe separado nesta rodada. |
| UI diante de resposta HTTP perdida | **FAIL** | nova chave no retry e conflito 409 sem reconciliação canônica. |

## Correções na branch noturna

Commits `1f11e1b`, `8cc20cc` e `f0a8691`: sessão e concessões revalidadas sob lock antes do commit; revisão de conteúdo sujeita aos grants de escrita e revisão; snapshots por versão na migração 0010; ledger armazena o snapshot pré-decisão e impede UPDATE/DELETE SQL; domínio filtrado antes da paginação; corrupção mapeada a 409; interface reconcilia resposta perdida e reutiliza chave de idempotência. Regressões novas em `test_review_api.py` e `audit-g5-review-ui.spec.ts`.

**Validação da branch noturna até este checkpoint:** API 183/183; web 66/66, typecheck/lint/build PASS; duas rodadas finais E2E 46/46 cada, sem retries. Uma rodada intermediária 43/46 falhou por preparação de grants duplicados no teste novo; corrigida e registrada, sem ocultação.

## Limites

Snapshots de revisões antigas já sobrescritas no banco anterior à migração 0010 não podem ser reconstruídos com segurança: leituras incompatíveis falham fechadas. O ledger ainda não é assinatura criptográfica contra um operador com acesso de escrita total ao arquivo SQLite. Grants e sessões continuam em memória de um processo. A correção noturna requer revisor distinto antes de qualquer aceite formal/merge.
