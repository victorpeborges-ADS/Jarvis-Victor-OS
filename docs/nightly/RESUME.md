# Retomada — sprint autônoma JARVIS

## Retomada pós-auditoria independente

- Candidate branch: `feat/jarvis-nightly-stabilization-2026-09-25`; base congelada: `fbaca45446f31258e7a121b3a49284516fcc8243`. Worktree: `/Users/vic/.codex/worktrees/jarvis-nightly-stabilization-2026-09-25/Jarvis-Victor-OS`.
- Leia [STABILIZATION_REPORT.md](STABILIZATION_REPORT.md) para o estado final, SHA, suites e limitações. Faça a nova auditoria em cópia somente leitura independente; não aceite Gate E a partir do relatório de implementação.
- Próximas verificações antes de dados reais: substituir coordenação de grants por garantia transacional compartilhada caso existam múltiplos workers; rever threat model do conector e escopo de catálogo; obter decisão de retenção e persistência das Missões. OAuth e contas reais seguem fora do escopo.
- Comandos de retomada após instalação por lockfile: `rtk uv run --locked pytest -q` em `apps/api`; `rtk npm test`, `rtk npm run typecheck`, `rtk npm run lint` em `apps/web`; E2E somente pelo runner `rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' JARVIS_E2E_SCREENSHOT_DIR='/tmp/jarvis-e2e-captures' npm run e2e`. Se portas loopback estiverem ocupadas, não interrompa processos alheios.

## Estado reproduzível

- Repositório original: `/Users/vic/Freela/Jarvis-Victor-OS`, base `e648e92467396ce67b75019858fbcd0ee5557042`. Não altere branch, arquivos ou untracked do original.
- Worktree: `/Users/vic/.codex/worktrees/jarvis-autonomous-sprint-2026-09-25/Jarvis-Victor-OS`.
- Branch: `feat/jarvis-nightly-2026-09-25-042315`; scaffolds desktop e Android em `1dd3c6c` e `5925e5f`. O commit documental final registra a entrega completa. Antes de atuar, leia `rtk git status --short` e `rtk git rev-parse HEAD`.
- Leia `docs/nightly/STATUS.md`, `EXECUTIVE_REPORT.md`, `TEST_MATRIX.md` e `GATE_E_AUDIT_AND_FIXES.md` antes de retomar. Não reexecute baseline completo sem necessidade.
- Documentos de plano mestre/histórico e prompt independente atual do Gate E não estavam presentes na cópia de trabalho; se o proprietário os disponibilizar nesta worktree, leia antes da revisão independente.

## Verificações locais

Com cwd `apps/api`:

```bash
rtk uv run --locked pytest
```

Com cwd `apps/web`:

```bash
rtk npm test
rtk npm run typecheck
rtk npm run lint
rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' npm run e2e
```

Com cwd `apps/mobile`:

```bash
rtk npm test
rtk npm run lint
rtk npm run build
rtk npm run e2e
rtk npx cap sync android
rtk npm audit
```

Com cwd `apps/desktop`:

```bash
rtk npm install
rtk npm run build
rtk npm audit
```

O frontend web desktop foi compilado, mas a shell Tauri não foi iniciada: `rustc` e Cargo não estavam disponíveis. O projeto Android foi criado e sincronizado com Capacitor, mas não há Android SDK/Studio, Gradle ou `adb`; portanto não existe `.app` ou APK. Quando os toolchains estiverem provisionados localmente, execute build nativo sem instalar dependências globais nem alterar a branch original.

O runner E2E exige origem de loopback allowlisted e banco descartável; não rode `npx playwright test` diretamente. Se a porta IPv6 loopback também estiver ocupada, não encerre processo alheio; registre o conflito e reagende o E2E. A porta IPv4 3000 pertenceu a outro workspace durante esta sessão.

## Próximas ações

1. Faça auditoria independente somente leitura da branch/commit, sem escrever na worktree do implementador; registre achados antes de aceitar Gate E.
2. Antes de dados reais, filtre o catálogo de calendários por grants e defina a semântica de GET/sync durante revogação concorrente; ver evidências no relatório de auditoria.
3. Decida se Missões precisa de persistência SQLite local. Se sim, proponha uma migração sintética, transacional e isolada com testes de reinício/concorrência, sem misturar fixtures DEMO. A implementação atual fica em `localStorage` e não promete sincronização.
4. Hosting ainda não selecionado. ADR 003 é documental e não prova compatibilidade nem custo; qualquer recurso cloud/billing depende de decisão explícita.
5. Frontends desktop/mobile e projeto Android Capacitor já estão criados e testados para web; retome a compilação nativa quando Rust/Cargo e Android SDK/Studio/Gradle/adb estiverem presentes, sem instalar toolchain global nem disputar recursos.

## Invariantes

- Somente dados sintéticos e processos de loopback; nenhuma conta externa, API LLM, n8n, OAuth, billing, deploy, túnel, push, merge ou tag de aceite.
- Não diga que o Gate E foi aceito: estado atual é **IMPLEMENTADO/TESTADO LOCALMENTE — AUDITORIA INDEPENDENTE PENDENTE**.
- Sessões/grants são voláteis; dados de Missões são locais no navegador; Calendar, provider e workflow são simulados; handoff não transmite.

## Retomada da candidata pós-auditoria

- Worktree: `/Users/vic/.codex/worktrees/jarvis-nightly-stabilization-2026-09-25/Jarvis-Victor-OS`.
- Branch: `feat/jarvis-nightly-stabilization-2026-09-25`; a execução final deve registrar o HEAD e confirmar árvore limpa. A worktree original permanece congelada em `fbaca45446f31258e7a121b3a49284516fcc8243`.
- Leia [STABILIZATION_REPORT.md](STABILIZATION_REPORT.md). Passe o commit final a um auditor independente como read-only. Não faça merge, push, deploy ou aceite automático.
- Reteste API: `rtk uv run --locked pytest` em `apps/api`; web: `rtk npm test`, `rtk npm run typecheck`, `rtk npm run lint`; E2E apenas via `rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' JARVIS_E2E_SCREENSHOT_DIR='/tmp/jarvis-e2e-captures' npm run e2e` em `apps/web`.
- As correções continuam limitadas a dados e bancos sintéticos locais; grants são coordenados em um processo, Missões ficam no localStorage, e Tauri/Android nativos não foram compilados.
