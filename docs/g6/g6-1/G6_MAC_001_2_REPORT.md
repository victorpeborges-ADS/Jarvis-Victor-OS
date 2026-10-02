# G6-MAC-001.2 — retorno de stop e falha pré-ready

## Baseline e escopo

- Branch: `feat/jarvis-g6-mac-001-2-stop-result-readiness-2026-10-02`.
- Baseline congelado: `7bbf6d733ed0736c8a5baad37a2f8e140a2447f8` (MAC-001.1).
- MAC-001 anterior: `c6fc5b9288e4569be8de95a4069c79eadce13f3f`.
- `main`: `82b3c244c796b68b181dbf127509caababd2258e`; G5 aceito: `ab7f856ee834b7f9923d914639e0e345dbf57322`.
- Escopo: somente retorno de `stop_and_wait` por geração e classificação de saída antes de readiness, no helper macOS local e sintético.

## Problemas reproduzidos e decisão

**P2-A.** MAC-001.1 já impedia `stop(A)` de parar ou esperar B, mas `wait_for_generation()` devolvia o snapshot global corrente. Com barreira entre término de A e retorno da thread de stop, os testes antigos exigiam `READY(B)`. MAC-001.2 mantém um objeto de conclusão por geração: A publica seu snapshot terminal antes de B poder substituir o status corrente. `stop_and_wait(A)` devolve A; `runtime_status()` devolve B. A UI consulta status separadamente após o comando. O contrato está em [`OPERATION_RESULT_CONTRACT.md`](OPERATION_RESULT_CONTRACT.md).

**P2-B.** EOF do stdout e saída do processo competiam. O supervisor verificava `try_wait()` uma vez e, se o child ainda aparecia vivo, matava-o e classificava o mesmo caso como `readiness_channel_closed`. Agora EOF é agregado com o estado observável do processo até o prazo de startup existente; saída anterior a READY é `child_exit_before_ready`, enquanto canal fechado com child vivo até o prazo é `readiness_channel_closed`. STOP continua aceito durante a agregação. O contrato está em [`PRE_READY_FAILURE_CONTRACT.md`](PRE_READY_FAILURE_CONTRACT.md).

## Validação executada

| Verificação | Resultado |
|---|---|
| `npm run build --prefix apps/desktop` | PASS, exit 0. |
| `node --test apps/desktop/tests/runtimeCommand.test.mjs` | PASS, 1/1. |
| `cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS, exit 0. |
| `cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS, exit 0. |
| Suíte `cargo test --locked` | Após atualização das asserções: 20 rodadas, cada uma com 42 passes, 0 failures e 4 ignored. |
| `child_exit_before_readiness_is_failed` isolado | 1.000/1.000 passes, 0 divergências. |
| Stress pré-ready ignorado | 1.000/1.000 passes, 22,61 s. |
| Stress start/stop ignorado | 1.000/1.000 passes, 21,08 s; resultado nunca menciona geração posterior. |
| Harness independente fora da worktree | 1.000/1.000 passes, 16,89 s; zero geração errada, timeout ou supervisor residual. |
| `npm --prefix apps/desktop run tauri -- build --no-bundle` | PASS, exit 0, 3m42s; executável release gerado. |
| `release_tauri_binary_is_spawned_and_reaped` | PASS, exit 0 após build release. |

Uma execução **intermediária** com o código novo e os testes herdados ainda exigindo `READY(B)` teve 32 passes, 2 failures e 3 ignored. As duas asserções foram corrigidas; não foi uma falha de classificação pré-ready nem foi ocultada por uma repetição verde. Os detalhes estão em [`FLAKINESS_TEST_MATRIX.md`](FLAKINESS_TEST_MATRIX.md).

## Fronteiras e riscos residuais

Nenhuma dependência foi adicionada. `apps/api`, migrações, ADR-010, contratos e proveniência G5, e lockfiles mantêm diff zero. Não há HTTP, porta do helper, serviço persistente, API G5, dados reais, OAuth, Android ou voz. O helper segue sendo um único child possuído pelo manager local; múltiplas instâncias do app não têm lock global. O prazo de startup delimita a classificação de EOF com child vivo. Garantia contra `SIGKILL` ou administrador do host continua fora deste subgate. Esta entrega prepara reauditoria independente; não aceita G6.1 nem inicia MAC-002.
