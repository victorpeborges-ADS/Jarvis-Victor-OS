# Retomada — G6-MAC-002

> Resumo histórico da MAC-002. A implementação vigente de lifecycle está em [RESUME_MAC_002_1.md](RESUME_MAC_002_1.md); a documentação de validação e limites está em [G6_MAC_002_1_REPORT.md](G6_MAC_002_1_REPORT.md).

## Candidata

- Branch: `feat/jarvis-g6-mac-002-local-transport-2026-10-02`
- Base: `main` em `00753c58b97c3103d428bc6a0a9351f97b6c050d`
- Worktree: `/private/tmp/jarvis-g6-mac002-local-transport-20261002`
- Escopo: native Tauri IPC → cliente Rust de rotas fixas → UDS HTTP → helper sintético supervisionado.

## Estado

O Runtime Manager cria UDS e capacidade exclusivos por geração; o pipe carrega ID, capability e identidade do diretório, sem path. O child valida CWD por `dev`/`inode` e faz bind relativo. Readiness e autenticação têm estados separados. O native client verifica health, versão e prova HMAC com nonce novo, incluindo operação sintética assinada. Stop/EOF revogam a sessão; cleanup do socket usa FD de diretório e `unlinkat`, mantendo o diretório vazio preservado. Não há FastAPI, G5, SQLite, migrations, TCP, OAuth, contas ou rede remota.

## Retomar a validação

Na worktree acima, executar:

```bash
npm run build --prefix apps/desktop
node --test apps/desktop/tests/*.test.mjs
cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
npm run tauri --prefix apps/desktop -- build --no-bundle
git diff --check
git fsck --full
```

O E2E Playwright existente é da aplicação web/API e iniciaria o runner/SQLite da API; ele não pertence à MAC-002 e não deve ser usado para executar G5. Verificar os probes de lifecycle e fake-process já incluídos na suíte nativa. Confirmar cleanup de processos/UDS e portas 3000/8000 após a rodada.

## Limites

Não executar/importar `apps/api`, não abrir SQLite, não instalar dependências, não integrar FastAPI, não alterar ADR-010, não criar listener TCP. Não fazer merge/push/tag/deploy. MAC-003 precisa autorização separada.
