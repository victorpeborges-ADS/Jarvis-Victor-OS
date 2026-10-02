# Retomada — G6-MAC-001.2

- Branch: `feat/jarvis-g6-mac-001-2-stop-result-readiness-2026-10-02`.
- Base exata: `7bbf6d733ed0736c8a5baad37a2f8e140a2447f8`.
- Correção: `stop_and_wait(A)` retorna o terminal de A mesmo após B iniciar; status corrente é consultado à parte.
- Classificação: saída antes de READY tem categoria e exit code próprios; EOF com processo vivo até o prazo permanece categoria distinta.
- Evidências: [`G6_MAC_001_2_REPORT.md`](G6_MAC_001_2_REPORT.md) e [`FLAKINESS_TEST_MATRIX.md`](FLAKINESS_TEST_MATRIX.md).
- Estado: candidata para reauditoria independente e decisão do proprietário. G6.1 não foi aceito; MAC-002 não começou.

## Revalidação

Na raiz da worktree:

```sh
npm run build --prefix apps/desktop
node --test apps/desktop/tests/runtimeCommand.test.mjs
cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml runtime_manager::tests::preready_tests::pre_ready_exit_classification_1000_rounds -- --ignored --exact --test-threads=1
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml runtime_manager::tests::linearization_tests::stress_start_stop_race_1000_rounds -- --ignored --exact --test-threads=1
npm --prefix apps/desktop run tauri -- build --no-bundle
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml runtime_manager::tests::release_tauri_binary_is_spawned_and_reaped -- --ignored --exact --test-threads=1
```

O entrypoint de helper é o quarto ignored e só deve ser executado como child de teste. Não conectar FastAPI, SQLite, rede, porta, CORS ou CSP neste subgate.
