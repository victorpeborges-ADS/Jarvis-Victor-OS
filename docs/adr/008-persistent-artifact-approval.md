# ADR 008 — aprovação persistente de artefatos e revisão humana

- Estado: proposta implementada para API local sintética, processo único.
- Data: 2026-09-25.
- Contexto: No Gate 4, o motor supervisionado passou a executar etapas determinísticas com registro em dois passos e recuperação de falha (SIGKILL), produzindo artefatos com `review_state: "draft"`. A aprovação humana existia apenas na camada DEMO do navegador (`localStorage`). O Gate 5 formaliza o ciclo de vida de revisão na API local sintética com persistência SQLite, autorização explícita e auditoria append-only.

## Decisão

1. **Separação estrita entre execução e revisão**:
   - Uma Missão atinge `status: "done"` quando todas as suas etapas determinísticas foram executadas com sucesso (`done`). A conclusão da execução não implica aprovação de artefatos.
   - Artefatos produzidos ingressam com estado de revisão `pending` (ou `draft` inicial). A decisão humana é uma mutação distinta e independente do ciclo de execução.

2. **Estados do ciclo de revisão**:
   - Estados canônicos: `pending`, `approved`, `rejected`, `changes_requested`.
   - Transições válidas:
     - `pending` -> `approved` | `rejected` | `changes_requested`
     - `changes_requested` -> nova versão do artefato com estado `pending`.
     - `approved` e `rejected` são terminais para a versão avaliada. Nenhuma mutação retroativa pode alterar a decisão registrada sobre aquela versão.

3. **Imutabilidade e versionamento de artefatos**:
   - Cada decisão de revisão é atrelada à tripla `(mission_id, artifact_id, artifact_version)` e ao seu hash criptográfico `artifact_sha256`.
   - Uma decisão `approved` aplica-se exclusivamente à versão exata avaliada pelo revisor. Se o artefato sofrer ajustes (versão 2), a versão 2 ingressa em `pending` e não herda aprovação da versão 1.
   - O ledger append-only `mission_review_decisions` registra um snapshot integral e verificável do artefato visto no momento da decisão.

4. **Concessão e autorização explícitas**:
   - Criado o recurso canônico `mission:review` sob o conector `mission_sim`.
   - Ter `mission:write` (permissão de execução) ou concessões de Calendar não confere autorização de revisão. Conhecer IDs também não autoriza.
   - A decisão exige que o domínio do artefato/missão esteja coberto por concessão `mission:review` ativa e não revogada.
   - Revalidação sob lock: a confirmação da decisão adquire `_grant_lock` em memória antes de abrir a transação SQLite `BEGIN IMMEDIATE` (`mission_review_confirmed`), garantindo que revogações ou expirações concorrentes impeçam o commit.

5. **Idempotência e concorrência**:
   - Decisões exigem `idempotency_key` e `expected_revision`.
   - Replay com a mesma chave e mesmo corpo devolve a decisão persistida (`replayed: true`).
   - Mesma chave com corpo diferente ou revisão divergente responde `409 Conflict`.
   - Duas decisões concorrentes sobre a mesma revisão são linearizadas no SQLite: a primeira comita e incrementa a revisão; a segunda falha com 409.
   - Rejeição e solicitação de ajustes exigem `reason` justificativo explícito (até 500 caracteres).

6. **Conhecimento staged**:
   - Conforme diretrizes deste gate, decisões de revisão não promovem automaticamente itens de `mission_knowledge` de `staged` para aprovados. A promoção de conhecimento permanece em `staged`, com garantia de não contaminação.

7. **Tratamento de dados corrompidos**:
   - Registros de revisão com integridade violada respondem 409 `integridade do registro de revisão` sem vazar dados sensíveis e sem remover linhas do banco.

## Limites

- Ambiente local, sintético e processo único.
- Sessão e concessões permanecem voláteis em memória; o reinício exige nova concessão `mission:review`.
- Não há autenticação biométrica ou SSO de identidade humana real; o ator registrado é o principal autenticado na sessão local.
- Não há propagação externa, mensageria nem garantia de exactly-once para efeitos fora do SQLite.
