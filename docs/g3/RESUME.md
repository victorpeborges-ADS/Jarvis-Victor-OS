# Retomada — G3

## Onde parou

Branch `feat/jarvis-g3-missoes-persistentes-p2`, worktree `/Users/vic/.codex/worktrees/jarvis-g3-missoes-persistentes-p2/Jarvis-Victor-OS`.

Commits de código, a partir de `main` `3214f9d`:

1. `86e1694` fix(calendar)
2. `092be84` feat(missions-contracts)
3. `10bd000` feat(api) persistência
4. `27bd5e7` feat(web) importação
5. `7460fd3` test(web) E2E da concessão renovada
6. `c38b1f5` feat(api) rascunhos antes de `done`

O commit deste arquivo é o HEAD candidato. Não houve merge, push, tag nem deploy.

## O que não fazer ao retomar

- Não integrar `fix/manutencao-whitespace` sem autorização.
- Não trocar a branch do checkout `/Users/vic/Freela/Jarvis-Victor-OS`.
- Não alterar as worktrees de formal, estabilização, sprint Nightly ou manutenção.
- Não usar o banco padrão do usuário. Testes usam SQLite temporário.

## Auditoria read-only sugerida

```bash
git -C /Users/vic/.codex/worktrees/jarvis-g3-missoes-persistentes-p2/Jarvis-Victor-OS status --porcelain=v1 -b
git -C /Users/vic/.codex/worktrees/jarvis-g3-missoes-persistentes-p2/Jarvis-Victor-OS rev-parse HEAD
git -C /Users/vic/.codex/worktrees/jarvis-g3-missoes-persistentes-p2/Jarvis-Victor-OS log --oneline 3214f9d..HEAD
git -C /Users/vic/.codex/worktrees/jarvis-g3-missoes-persistentes-p2/Jarvis-Victor-OS diff --stat 3214f9d..HEAD
```

Suítes, se forem repetidas, devem usar a worktree acima, `uv run --locked pytest -q` em `apps/api` e `npm test` / `npm run e2e` em `apps/web`, com captura fora do repositório. Não abrir porta pública e não reutilizar o processo que já escuta `*:3000`.
