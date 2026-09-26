# Relatório executivo — G5

Parecer do implementador. Não substitui auditoria independente e não autoriza merge na `main`.

## Baseline reproduzida antes das mudanças

No commit `8e7c09bb303deb6fe444a3a455961519a5f414d2`, worktree nova e isolada:

- pytest: 167/167 PASS
- Vitest: 64/64 PASS
- typecheck: PASS
- lint: PASS
- build web: PASS
- E2E web desktop/mobile: 40/40 PASS (exit code 0)

## Escopo e Entrega G5

A branch `feat/jarvis-g5-aprovacao-persistente` implementa o ciclo de aprovação humana persistente de artefatos no SQLite da API local sintética.

### Classificação do escopo

- **IMPLEMENTADO**:
  - Migração incremental `0009_artifact_reviews.sql` com tabelas `mission_artifact_reviews` e `mission_review_decisions`, índices e integridade referencial.
  - Recurso canônico `mission:review` sob o conector `mission_sim`, isolado de `mission:write` e de `calendar_sim`.
  - Guarda transacional `mission_review_confirmed` que lineariza `_grant_lock` antes do SQLite `BEGIN IMMEDIATE`, eliminando janela de revogação/expiração.
  - Endpoints REST `/real/reviews`, `/real/reviews/{id}`, `/real/reviews/{id}/decide`, `/real/reviews/{id}/revise` e `/real/missions/{id}/reviews`.
  - Tratamento de idempotência com chave monotônica e corpo; replays retornam a mesma decisão com `replayed: true`.
  - Versionamento imutável de artefatos: aprovação atrelada à tripla `(mission_id, artifact_id, artifact_version)` e ao hash SHA-256 do conteúdo.
  - Solicitação de ajustes (`changes_requested`) com motivo obrigatório e submissão de nova versão imutável (`v2`) que ingressa em `pending`.
  - Ledger append-only de decisões com snapshot verificável do artefato avaliado.
  - Atualização do painel web de Missões com seção de fila de revisão, diálogo de inspeção de conteúdo e controles de decisão.
  - ADR 008 em `docs/adr/008-persistent-artifact-approval.md`.

- **TESTADO**:
  - 178 testes no pytest da API, incluindo suíte de 10 testes dedicados em `test_review_api.py`.
  - 66 testes no Vitest web, incluindo testes de requisições de revisão e headers CSRF.
  - Probes adversariais de concorrência, revogação/expiração em pausa (falha fechada), rollback, cross-principal, integridade corrompida e SIGKILL/restart.
  - 42 testes no Playwright E2E em **duas rodadas completas consecutivas sem retries** (exit code 0 em ambas).
  - Probes críticos do G4-R1 revalidados (cancelamento e revogação antes do commit sem novos artefatos).

- **DEMO**:
  - A marcação humana de aprovação local na página DEMO (`localStorage`) permanece isolada e não interfere nas tabelas SQLite da API.

- **NÃO IMPLEMENTADO**:
  - SSO ou identidade humana biométrica real.
  - Notificações externas ou mensageria.
  - Aplicativos móveis nativos compilados (Android/iOS).

- **BLOQUEADO**:
  - Promoção automática de `mission_knowledge` para estado aprovado: mantido expressamente em `staged`, com barreira de segurança até que invariantes de conhecimento sejam contratados em gate futuro.
  - Autenticação de múltiplos operadores humanos reais independentes: bloqueado pelo modelo de sessão monoprocésso local (`owner`).
