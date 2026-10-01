# Matriz de testes e evidências

## Suíte Rust

Comando normal:

```sh
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Resultado registrado: **23 passed, 0 failed, 2 ignored**. Um ignored é o entrypoint usado somente como child isolado dos testes; o outro é a prova do binário Tauri de release abaixo.

| Caso | Resultado esperado e evidência |
|---|---|
| `stopped_starting_ready_stopping_stopped` | Estados e handshake válidos; PID informativo presente. |
| Startup lento | Timeout termina e recolhe child; categoria `startup_timeout`. |
| Saída antes/depois de readiness | `FAILED` versus `CRASHED`, com código preservado. |
| Readiness errada, obsoleta, inválida ou duplicada | IDs não correspondentes são ignorados; duplicata não repete transição. |
| stdout fechado antes de prontidão | `FAILED` e child recolhido. |
| Stop durante startup/pronto e stop duplicado | Encerramento idempotente; sem child nem supervisor residual. |
| Start duplicado/concurrente | Exatamente uma instância por manager; segunda chamada rejeitada. |
| Restart após crash | Somente explícito; novo ID de instância. |
| Restart após parada normal | Rejeitado; não vira start implícito. |
| Shutdown travado | Kill pelo handle, `wait()`, estado terminal e categoria de timeout. |
| Start/stop e restart/stop simultâneos | Operações serializadas e sem processo residual. |
| Processo independente | Sobrevive a start, stop, crash e restart do child gerenciado. |
| Argumentos | Lista fixa; comandos de shell não são aceitos como modo. |

Prova pós-build, executada explicitamente:

```sh
cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml -- --ignored --exact runtime_manager::tests::release_tauri_binary_is_spawned_and_reaped
```

Resultado: **1 passed**. RuntimeManager iniciou `target/release/desktop` com o modo interno normal, validou READY e chamou stop/reap.

## Builds e higiene

| Comando/inspeção | Resultado |
|---|---|
| `npm run build --prefix apps/desktop` | PASS: `tsc` e Vite. |
| `cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS. |
| `cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS. |
| `npm --prefix apps/desktop run tauri -- build --no-bundle` | PASS: executável de release; sem `.app`, assinatura ou notarização. |
| Smoke de READY/ACK/STOP no executável de release | PASS; saída 0. |
| `git diff --check` | PASS. |
| Busca por helpers residuais após testes | Nenhum encontrado. |
| `lsof` em TCP 3000 e 8000 após execução | Nenhum listener encontrado. |

## Não executado

- Não abriu janela Tauri e não fez inspeção visual/manual do IPC.
- Não gerou capturas de tela.
- Não rodou API, Vitest, E2E ou probes G5: os arquivos e caminhos do backend não mudaram e a UI deste subgate não chama API.
- Não empacotou `.app`, não assinou e não notarizou.

Estas ausências limitam o que esta prova aceita; não são evidência de G6.1 integrado.
