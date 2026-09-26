# Segundo olhar independente — G5 e caminho noturno

**Revisor:** agente distinto, somente leitura, sem edição e sem execução de testes. O parecer é revisão estática independente da autoauditoria e dos testes dinâmicos do executor principal. **Não é aceite formal do proprietário.**

## G5 congelado `4931c56`

**Veredito: NÃO ACEITÁVEL.** O revisor confirmou no código: decisão após logout durante pausa porque o token não chegava ao guard; paginação antes do filtro de domínio autorizado; reconstrução da revisão histórica usando o conteúdo atual, fazendo v1 devolver corpo v2 sob hash v1; snapshot do ledger capturado após mutação. A autoauditoria dinâmica em `G5_AUDIT.md` também reproduziu esses e outros defeitos. O candidato congelado permaneceu intacto.

## Branch noturna

Na primeira leitura do SHA `eddeda3`, o revisor apontou:

| Gravidade | Achado | Correção e prova |
|---|---|---|
| Alta | `run`/`resume` confirmavam artefato após logout porque `mission_write_confirmed` não recebia o token da sessão. | `2b79940`: token passado por rota → repositório → motor até o guard do commit. Testes dinâmicos novos pausam execução, fazem logout ou revogam grant e exigem 403 sem artefato. |
| Alta | `create`, `cancel`, `fail`, `retry`, `import` tinham pré-checagem de grant sem proteção até a transação. | `2b79940`: guard de sessão/grant cobre a transação; import segura todos os domínios aceitos em ordem estável. Testes dinâmicos revogam grant entre pré-checagem e mutação. |
| Média | `GET /sources` mostrava `awaiting_review` permanentemente, inclusive após aprovações. | `2b79940`: retorna `selection_state=selected` separado de `artifact_review_state` e `knowledge_state`; teste observa a transição de pendente para aprovado. |

O segundo olhar final, também estático, no commit `2b79940` considerou esses achados resolvidos no ponto de commit e não encontrou nova falha alta nos caminhos alterados. **Limite:** a execução ainda grava fase transitória `open/running` antes da revalidação final; se a sessão cair, estaciona como `interrupted`, sem confirmar artefato. Testes dinâmicos executados pelo agente principal: API completa **197 PASS**. Rodadas E2E completas finais estão em `TEST_MATRIX.md`.

**Aceite:** o G5 congelado segue FAIL; a branch noturna permanece candidata revisável, sujeita a auditoria formal e aprovação humana antes de merge.
