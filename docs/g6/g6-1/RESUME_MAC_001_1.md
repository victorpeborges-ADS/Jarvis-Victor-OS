# Retomada — G6-MAC-001.1

## Estado

- Branch local: `feat/jarvis-g6-mac-001-1-linearized-stop-2026-10-02`.
- Baseline direto: `c6fc5b9288e4569be8de95a4069c79eadce13f3f`.
- Commit fix: `aee1aed8a7d9a35de0694af8e1dff75e1bb3c430`.
- Commit tests: `3b6fe7dc3ec4462896b1723c849359f111ced82f`.
- Objetivo executado: impedir que um `stop_and_wait` de uma geração observe, pare ou espere implicitamente uma geração posterior.
- Evidência principal: reprodução determinística do P2 no baseline, testes de barreira no patch e stress start/stop de 500 rodadas.
- Estado de produto: encaminhar MAC-001.1 para reauditoria/decisão do proprietário. G6.1 não foi aceito. MAC-002 permanece não iniciado.

## Como validar novamente

Na raiz do repositório:

```sh
npm run build --prefix apps/desktop
cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
npm --prefix apps/desktop run tauri -- build --no-bundle
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml \
  runtime_manager::tests::release_tauri_binary_is_spawned_and_reaped \
  -- --ignored --exact
```

Execute o teste ignored de release depois do build nativo. Para stress separado, use o comando em [`CONCURRENCY_TEST_MATRIX.md`](CONCURRENCY_TEST_MATRIX.md).

## Fronteira

Não conectar API Python, SQLite, CORS, CSP, origem ou portas neste subgate. Não iniciar MAC-002, nem ampliar para Android, voz, serviços ou persistência. O próximo passo após o handoff é reauditoria independente do SHA final desta branch e decisão explícita de aceite.
