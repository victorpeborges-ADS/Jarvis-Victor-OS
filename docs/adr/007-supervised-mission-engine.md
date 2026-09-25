# ADR 007 — motor supervisionado de Missões

- Estado: proposta implementada para API local sintética, processo único.
- Data: 2026-09-25.
- Substitui, no servidor, a lista de transições do ADR 006. O DEMO do navegador não é este motor.

## Estados

O estado da missão continua no documento v1. `done` permanece o estado concluído; não há um segundo valor `completed`.

```mermaid
stateDiagram-v2
    planned --> running: run_next abre execução
    running --> running: commit da etapa
    running --> done: última etapa confirmada
    running --> interrupted: boot encontra execução aberta
    interrupted --> running: resume autorizado
    interrupted --> failed: fail
    failed --> planned: retry explícito
    planned --> cancelled: cancel
    running --> cancelled: cancel
    interrupted --> cancelled: cancel
    failed --> cancelled: cancel
```

A etapa tem estado próprio. `done` da missão só ocorre quando todas as etapas estão `done` e cada uma tem artefato `draft` rastreável.

## HTTP

`POST /real/missions/{id}/transition` aceita `run_next`, `resume`, `fail`, `retry` e `cancel`, com `expected_revision` e `idempotency_key`. A resposta inclui `available_actions` calculadas pelo servidor. Grant de Calendar não autoriza. `mission:write` é revalidado antes de confirmar a etapa.

## Concorrência

Uma execução `open` por missão. A transição vencedora grava artefato, etapa, revisão e evento na mesma transação final. A outra recebe 409. Chave igual com corpo diferente também recebe 409.

## Interrupção

`run_next` confirma a linha `open` antes do trabalho determinístico. Se o processo morre nessa janela, o boot marca a execução e a missão como `interrupted` e não relança a skill. `resume` explícito, com grant vigente, conclui a mesma etapa. O identificador do artefato é estável para não duplicar.

## O que não é este motor

Não há fila, segundo worker, scheduler nem efeito externo. `fail` aqui é a ação explícita ou a falha da skill no processo vivo, não uma aprovação humana. Aprovar artefato continua só no DEMO do navegador.
