# Aprovação amarrada e outbox sintética — 2026-10-17

Candidata `636d5bd`, worktree `codex/jarvis-integration-candidate`. Banco diário não foi aberto. Nada disso autoriza conta real, OAuth, rede, shell ou escrita externa.

## O que o banco sintético garante

A aprovação de `simulate_action` grava, por 60 segundos, o hash exato do objeto (`arguments_sha`), a conta `operator@example.test`, o conector `synthetic-mail`, a ferramenta, o destino `synthetic-outbox` e o efeito apresentado (texto do catálogo mais a consequência da prévia). O hash desses campos fica em `binding_sha`.

Se a aprovação expira, ou se a revisão, a conta, o conector, a ferramenta, o destino ou o efeito apresentado mudam depois, a execução é recusada e o ledger não recebe linha. Cancelar ou pausar também não registra efeito. Uma aprovação repetida do mesmo objeto não cria outra concessão. Troca parcial da linha de aprovação invalida o hash e o efeito não ocorre.

`send_message`, `pay`, `delete_record` e `invite_member` continuam desligadas. A migration `0021_effect_approval_outbox.sql` só acrescenta colunas e as tabelas da outbox; as migrations 0001–0020 não foram editadas.

## O que a outbox falsa prova

O conector falso só faz `INSERT OR IGNORE` em `synthetic_effect_ledger`. Não abre socket nem processo. A outbox mostra `succeeded`, `failed` ou `unknown`.

Sucesso grava um efeito e a repetição devolve o mesmo resultado. Falha explícita não grava ledger. Timeout ou ack perdido deixa `unknown`. A reconciliação não chama o conector: se o ledger já tem a chave, marca sucesso sem segunda linha; se não tem, marca falha. Concorrência e replay mantêm uma única linha. Cancelar a tarefa depois de um efeito já gravado não muda a outbox para cancelada.

Automações locais continuam só no SQLite: criar, executar, pausar, retomar e excluir preservam o histórico e não escrevem na outbox.

## O que continua bloqueado

Efeito externo real, conta real, OAuth, Gmail, Drive, GitHub, rede e shell. Não há rota nova: Rust e TypeScript não foram alterados, então a janela não exibe o estado da outbox. Smoke visual da janela: BLOCKED. Voz, Android e sync: fora deste trabalho.

O pytest `test_lexical_search_does_not_add_fts_or_a_migration` exige a ausência de `0021*`. Esse arquivo é de outro fluxo e não foi editado. A migration 0021 existe; o sentinel desse teste fica vermelho por isso.
