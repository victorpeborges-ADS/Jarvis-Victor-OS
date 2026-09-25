# ADR 006 — registro persistente de Missão

- Estado: aceito para API local sintética, processo único.
- Data: 2026-09-25.

## Decisão

O documento `Mission` v1 continua sendo o corpo compatível com o `localStorage` DEMO. A durabilidade no SQLite usa o envelope `MissionRecord`: `dataset=api_synthetic`, `owner` do principal da sessão, `revision` monotônica e `access_class=synthetic_local`. O cliente não escolhe o owner.

Transições válidas no servidor, na mesma transação do evento append-only:

- `planned` ou `running` pode executar `run_next` quando as dependências estão `done`.
- `done` só ocorre quando todas as etapas estão `done`.
- `cancel` vale a partir de qualquer estado que não seja `done` nem `cancelled`.
- `fail` e `retry` são ações da API desde o motor G4, descritas no ADR 007. A marcação humana que aprova um artefato continua apenas na página DEMO do navegador e não existe como transição da API.

`expected_revision` divergente responde 409 e não grava. Chave de idempotência repetida com o mesmo corpo devolve o mesmo registro; corpo diferente responde 409.

## Limites

Um grant `calendar_sim` não autoriza Missão. A capacidade mínima é o conector `mission_sim`, com recursos `mission:read` e `mission:write`, separados. Não há worker durável: a etapa roda dentro do pedido HTTP. Não há resistência multiworker nem sync entre dispositivos.
