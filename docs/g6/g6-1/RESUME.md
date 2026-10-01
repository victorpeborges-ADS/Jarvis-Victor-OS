# Retomada após G6-MAC-001

## Estado de origem

- Repositório: `Jarvis-Victor-OS`
- Branch: `feat/jarvis-g6-1-macos-runtime-foundation-2026-10-01`
- Baseline de implementação: `59c3b28103bef2fb0ce518826bcca834b43dccd2`
- `main` que foi confirmada: `82b3c244c796b68b181dbf127509caababd2258e`
- G5 formalmente aceito: `ab7f856ee834b7f9923d914639e0e345dbf57322`
- Relatório: [`G6_MAC_001_REPORT.md`](G6_MAC_001_REPORT.md)

Use a branch e worktree existentes. Não crie worktree/branch paralela para o próximo passo; confirme `git status`, branch, baseline e ancestry antes de continuar.

## O que já está provado

O binário Tauri sem bundle compila. O mesmo supervisor inicia esse executável como helper sintético, valida o ID na readiness e o recolhe após stop. A suíte adversarial do manager passa. As ações da UI são fixas e não contêm payload de processo.

## Próxima etapa: G6-MAC-002

Definir transporte/endpoint, ownership do listener, porta e origin do WebView. Provar colisão de porta e processo falso, CSP, CORS, Host, Origin, CSRF e cookie no artefato alvo antes de habilitar API autenticada. A prontidão futura deve comprovar o processo/endpoint e o estado real necessário, incluindo banco/migrações. Não interpretar este helper como esse contrato.

G6-MAC-003 deve empacotar o runner oficial `python serve.py` e definir proteção/recuperação do banco em dados sintéticos. Sessões e grants continuam voláteis conforme ADR-010. Não habilitar multiworker, conta real, OAuth, rede remota ou deploy sem decisão e autorização próprias.

## Comando útil de retomada

```sh
cd apps/desktop
npm run build
npm run tauri -- build --no-bundle
cd ../..
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Para repetir a prova pós-build, rode o comando ignorado documentado em [`TEST_MATRIX.md`](TEST_MATRIX.md). O teste ignorado do entrypoint interno não deve ser executado sozinho sem as variáveis de ambiente esperadas pelo harness.
