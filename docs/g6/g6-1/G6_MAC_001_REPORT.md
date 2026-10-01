# G6-MAC-001 — relatório de lifecycle local supervisionado

## Identificação

- Branch: `feat/jarvis-g6-1-macos-runtime-foundation-2026-10-01`
- Baseline: `59c3b28103bef2fb0ce518826bcca834b43dccd2`
- `main` observada: `82b3c244c796b68b181dbf127509caababd2258e`
- G5 aceito: `ab7f856ee834b7f9923d914639e0e345dbf57322`, ancestral do baseline
- Commits locais de código: `57933733742d98896b6e6b525e60debc3702c9f4` e `85b12cb` (teste do executável release)
- Escopo: helper sintético iniciado pelo executável Tauri, sem integração à API ou a dados do produto

## Resultado

O `RuntimeManager` inicia o executável atual sem shell, mantém o handle `Child` em um supervisor, exige uma linha de readiness que corresponda ao ID da tentativa, envia ACK, aceita parada cooperativa, aplica timeout e recolhe o processo. Estados e erros ficam disponíveis em uma seção pequena “Runtime local” do aplicativo. Os comandos Tauri não recebem parâmetros.

Os modos adversariais existem apenas em `cfg(test)`. O executável de produção aceita somente o modo interno fixo `normal`. Em uma prova pós-build, o mesmo supervisor iniciou `target/release/desktop`, recebeu o handshake e fez stop/reap.

## Arquitetura e ownership

- O manager guarda snapshot e canal de controle protegidos por mutex/condvar.
- Uma thread supervisora é proprietária do `Child`, do stdin e da espera/recolha.
- Uma thread lê stdout e encaminha linhas ao supervisor; somente a linha exata `JARVIS_RUNTIME_READY <id-atual>` é aceita.
- O manager gera um ID novo por tentativa. PID serve apenas para diagnóstico e nunca é usado para localizar ou sinalizar processo.
- O lançamento usa `Command::new(current_exe())`, ambiente limpo, três argumentos fixos, stdin/stdout em pipe e stderr descartado. Não há shell.
- Parada escreve `JARVIS_RUNTIME_STOP <id>`, espera até 700 ms e, se necessário, mata somente o `Child` retido e chama `wait()`.
- O encerramento normal do app chama `stop_and_wait`. Não há reinício automático.

O protocolo completo está em [`READINESS_CONTRACT.md`](READINESS_CONTRACT.md), a tabela de transições em [`RUNTIME_STATE_MACHINE.md`](RUNTIME_STATE_MACHINE.md) e as garantias de ownership em [`PROCESS_OWNERSHIP.md`](PROCESS_OWNERSHIP.md).

## Evidências de validação

| Verificação | Resultado |
|---|---|
| `npm run build --prefix apps/desktop` | PASS; TypeScript e Vite compilaram a UI. |
| `cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS. |
| `cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS. |
| `cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS: 23 passaram, 2 helpers internos ignorados, 0 falhas. |
| `cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml -- --ignored --exact runtime_manager::tests::release_tauri_binary_is_spawned_and_reaped` | PASS: o supervisor iniciou e recolheu o binário de release. |
| `npm --prefix apps/desktop run tauri -- build --no-bundle` | PASS; gerou o executável Tauri de release. Não gerou `.app` nem assinatura. |
| Smoke do helper do binário release via stdin/stdout | PASS: READY com ID fornecido, ACK, STOP, saída 0. |
| `git diff --check` | PASS. |
| inspeção de processos auxiliares e listeners TCP 3000/8000 | Nenhum helper residual ou listener encontrado após as provas. |

A lista individual de casos e limitações está em [`TEST_MATRIX.md`](TEST_MATRIX.md). A UI foi compilada, mas não foi aberta em janela Tauri; os comandos IPC não foram clicados manualmente. Não há capturas de tela desta execução.

## Fronteira e threat model local

Ativos protegidos nesta prova: ownership correto do processo child e integridade do estado exibido. A ameaça operacional coberta é uma falha de inicialização, linha stale/falsa, crash, chamada duplicada, corrida start/stop, shutdown travado ou tentativa de terminar processo alheio. Testes verificam essas condições e confirmam que um processo sintético independente sobrevive.

O ID da instância é identificador fresco para correlação, não segredo criptográfico. O PID é informativo. O modelo confia no usuário e no host local; um administrador do host ou processo suficientemente privilegiado pode inspecionar ou alterar binários e memória. O lifecycle cobre saída normal do app, não promete limpeza após `SIGKILL`, queda de energia ou encerramento forçado do host.

Não há endpoint, socket, porta, API, SQLite, sessão, grant, fixture DEMO, dado pessoal, conta real, OAuth, voz ou serviço persistente. G5 e ADR-010 não foram alterados. G5 não é formalmente reavaliado por esta entrega.

## Limitações e riscos residuais

- Build Tauri `--no-bundle` prova o executável nativo, não o `.app`, assinatura, notarização, comportamento dentro do bundle nem instalação.
- A prova não é a API Python final e não prova readiness de banco/migração.
- Uma instância do manager impede children duplicados naquela instância; não existe lock global de múltiplas instâncias do aplicativo.
- Encerramento abrupto do processo pai não está coberto por handlers de saída normal. O helper atual não cria grandchildren.
- Nenhuma regressão de API, E2E do produto ou inspeção visual manual foi necessária ou executada, pois o backend e o fluxo de produto permanecem desconectados.

## Sequência e próximo subgate

As decisões e arquivos alterados ficam na branch local indicada. Para retomar, consulte [`RESUME.md`](RESUME.md). G6-MAC-002 deve resolver endpoint/porta/origin, colisão, origem falsa e CSP/CORS antes de conectar qualquer operação protegida. O estado deste relatório não marca G6.1 completo.
