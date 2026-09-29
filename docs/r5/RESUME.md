# R5 — Retomada e auditoria

1. Confirme branch `feat/jarvis-unified-r5-2026-09-27`, HEAD e diretório limpo com `git status --short --branch` e `git rev-parse HEAD`.
2. Leia [ADR-009](../adr/009-trusted-source-and-review-state.md), [invariantes](TRUSTED_STATE_INVARIANTS.md), [modelo de ameaças](THREAT_MODEL_LOCAL.md) e [matriz](TEST_MATRIX.md).
3. Execute a regressão indicada na matriz; repita as duas rodadas E2E com `--retries=0` e guarde exit codes/stdout/stderr e screenshots na pasta de evidências em `docs/r5/`.
4. Confira os diffs para R4 congelada `59d8598cf733f9db4c7f6ca31c1b3b2bc7b8d03e` e para a main registrada nesta tarefa. Não misture outra worktree.
5. Registre no relatório os SHAs completos dos commits atômicos, captura das dimensões exigidas, testes e limitações. Reconfirme que não há listeners residuais.

Não faça merge, push, tag, deploy, login de conta real, instalação persistente ou aceite formal G5. R5 permanece local e não é uma autorização para ampliar o modelo de segurança.
