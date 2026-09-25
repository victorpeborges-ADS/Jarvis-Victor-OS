# Relatório executivo — G4

Parecer do implementador. Não é auditoria independente e não autoriza merge.

## Baseline reproduzida antes das mudanças

No commit `9c97dad3639df50aa2936c063c63e3d3cf045828`, worktree nova:

- pytest 157/157
- Vitest 64/64
- typecheck PASS
- lint PASS
- E2E web 36/36

## Entrega

Branch `feat/jarvis-g4-execucao-supervisionada`. A `main` não foi movida. A manutenção `a6cd0ff` não entrou.

O motor confirma a execução aberta antes da skill. Se o processo morre nessa janela, o boot marca `interrupted` e só `resume` autorizado conclui a etapa, sem segundo artefato. `done` continua sendo o estado concluído.

## Fora deste escopo

Execução autônoma contínua, apps nativos, dados pessoais, OAuth, hospedagem remota e múltiplos workers não foram aprovados nem implementados.

## R1 — corrida de cancelamento e revogação

Este relatório, a partir daqui, descreve a branch `feat/jarvis-g4-r1-cancel-revoke`. Não move `main` e não altera `78d4e882a5f3f3745805025eb22d04349e2ca0a6`.

O `run_next` antigo só confirma uma execução que continua `open`, com a mesma revisão. O `resume` só confirma a fase `interrupted`. Cancelamento e `fail` fecham a execução aberta como `failed`. A revalidação de `mission:write` ocorre com o lock da concessão retido até o fim do `BEGIN IMMEDIATE`.

Evidência dos dois cenários que falharam na auditoria do `78d4e88`:

- Cancelamento confirmado durante a pausa, depois a skill antiga liberada: a execução em voo responde 409, a missão permanece `cancelled` e não há artefato novo.
- Revogação de `mission:write` confirmada durante a pausa, depois a skill liberada: a execução em voo responde 403, a missão fica `interrupted` e não há artefato. `resume` sem grant novo responde 403. Com grant novo, um único artefato é gravado; a segunda retomada não duplica.

Suítes nesta worktree: pytest 167/167, Vitest 64/64, typecheck PASS, lint PASS, build PASS, E2E desktop e mobile 38/38.
