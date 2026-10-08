# Fechamento local G6 — MAC-002.2 e MAC-003

Este documento registra o estado da branch `feat/jarvis-g6-final-closeout`. Não é aceite formal, não autoriza merge, push, tag ou deploy, e a revisão feita em seguida no mesmo trabalho é interna.

## Baseline

- Base documental aceita: `bf575be1645578eebedd41cddd3463b75726776b` (`main`).
- MAC-002.2 de partição CTR: `f05e19222ee6d3ae58769632c2cea2470f109f86`.
- Branch auditada de replay: `feat/jarvis-g6-mac-002-2-replay-lifecycle-fix` em `2cd1661d1e43cb73630cfd0e62f50704fec0ef40`.
- A worktree nova parte de `2cd1661` e incorpora o commit de espera do envio que já existia em `6556170`, refeito aqui como `47c130a`.

## Corrida de envio

`deactivate` adquire o lock da transação G5 antes do mutex da capability. A transação segura esse lock desde `ensure_active` até a escrita e a abertura da resposta. Quem chega depois da desativação falha antes de conectar. O teste `g5_transaction_barriers_cover_admission_seal_and_prewrite_check` para em `admitted` e em `sealed`; `inflight_send_finishes_before_deactivate_and_later_send_writes_nothing` para em `checked`, imediatamente antes do `write_all`, e em `received`, depois que a resposta HTTP já foi lida e antes de `open_application_response`. Os dois ordenamentos passam. Depois que `deactivate` retorna, o segredo está vazio, a sequência fica em `u64::MAX` e não há nova conexão.

Uma execução intermediária travou: a chamada de controle depois da desativação reentrou na barreira de admissão no mesmo fio. A checagem de atividade passou a ocorrer antes dessa barreira, e o gancho é removido antes da chamada de controle. A repetição passou em 0,06 s.

## Intervalo pós-leitura

A reauditoria de `149f927` não encontrou defeito nesse intervalo, e apontou que nenhuma barreira segurava o fio depois da leitura e antes de `open_application_response`. A branch `feat/jarvis-g6-final-response-barrier` parte desse SHA e acrescenta só o gancho de teste `received`. Ele dispara com `request_lock` ainda seguro, filtra a fase e não espera nas fases `admitted`, `sealed` ou `checked`. O marcador `opened` registra o fim da abertura sem esperar, ainda dentro do mesmo guard. O teste `inflight_send_finishes_before_deactivate_and_later_send_writes_nothing` observa `deactivate` bloqueado enquanto a resposta está pausada, a ordem `opened` e só então `deactivated`, e uma chamada seguinte que retorna `Inactive` sem novo `accept` no listener que continua vivo. O gancho é removido antes dessa chamada. Isso não altera o formato v3 nem o caminho de produção. O smoke da WebView continua aberto e sem aceite formal.

## Gates ainda abertos

| Gate | Estado nesta rodada | Evidência |
|---|---|---|
| P1 de keystream CTR v3 | Fechado antes; regressão repetida | `test_native_ctr_partition.py`; testes Rust de partição e interoperabilidade |
| P3 de replay antes do CTR | Fechado em `2cd1661` | reserva antes da cifra; suíte nativa |
| P3 de sequência viva na desativação | Fechado em `2cd1661` | `deactivation_is_synchronized_and_concurrent_seals_do_not_reuse_sequence` |
| P3 de envio depois da checagem | Fechado nesta branch | barreiras `admitted`, `sealed`, `checked` e `received` |
| HMAC antes de descriptografar, replay e overflow | Fechado | suítes Python e Rust |
| Substituição same-UID e `LOCAL_PEERPID` | Fechado no supervisor | sonda `health=200;version=200;proof=200;open=404;...;read=404` |
| Isolamento por geração, sessão e grant | Fechado no supervisor e nos testes de cache | STOP, EOF, crash, restart e nova sessão sem grant |
| Autorização G5, consentimento e revogação | Fechado no manager e no FastAPI | leitura sintética, revogação, negativa local e negativa do servidor |
| Listener TCP | Ausente no launcher e no transporte | UDS `runtime.sock`; sem bind TCP no caminho desktop |
| Smoke Tauri/WebView | **BLOCKED** | `System Events` retornou `UI elements enabled = false` |
| Empacotamento distribuível | **BLOCKED** | o launcher de release usa `CARGO_MANIFEST_DIR` e a passphrase do ambiente |
| Aceite formal, merge, push, tag, deploy | Não feitos | — |

## Smoke manual

O controle de observação da janela está desligado. Não alterei Acessibilidade e não iniciei uma janela que não poderia ler. O binário local, já com o botão de tentativa, está em:

`apps/desktop/src-tauri/target/release/desktop`

Prepare um banco sintético fora do repositório. Invente uma passphrase de 12 a 128 caracteres só para esta execução e não a grave no git.

```bash
cd /Users/vic/.codex/worktrees/jarvis-g6-final-closeout/Jarvis-Victor-OS
SCRATCH="$(mktemp -d)"
chmod 700 "$SCRATCH"
export JARVIS_DATABASE_PATH="$SCRATCH/synthetic.sqlite3"
export JARVIS_LOCAL_PASSPHRASE
read -r -s -p "Passphrase sintética: " JARVIS_LOCAL_PASSPHRASE
echo
apps/api/.venv/bin/python -B -c "from memory_store import SQLiteMemoryStore; from mission_repository import MissionRepository; import os; store=SQLiteMemoryStore(os.environ['JARVIS_DATABASE_PATH']); store.initialize(); MissionRepository(store).create('owner', 'Missão sintética MAC-003', 'dom_synthetic_a', 'mac003-manual-smoke')"
open apps/desktop/src-tauri/target/release/desktop
```

Na janela, registre só o texto visível. Não capture a passphrase, tokens ou o caminho do socket.

1. Em **Runtime local**, clique **Iniciar**. Espere **Pronto** e canal **Autenticado**, protocolo 3.
2. Em **Missões**, digite a passphrase e clique **Abrir sessão local**. O campo deve esvaziar. O texto deve dizer **Sessão aberta** e ainda não **Concessão ativa**.
3. Marque a confirmação de `dom_synthetic_a` e clique **Conceder leitura**.
4. Clique **Ler uma missão sintética**. A missão **Missão sintética MAC-003** deve aparecer, com `dom_synthetic_a`.
5. Clique **Revogar concessão**. O estado de concessão ativa deve sumir.
6. Clique **Tentar leitura sem concessão**. A negativa visível é `A concessão de leitura está ausente ou expirada.` Nenhum cartão de missão deve permanecer. Esconder o botão de leitura não substitui este clique.
7. Clique **Encerrar sessão e invalidar concessão**.
8. Abra a sessão de novo com a mesma passphrase. A concessão não deve voltar marcada. Repita **Tentar leitura sem concessão** e confirme a mesma negativa.
9. Encerre a sessão e, em **Runtime local**, clique **Parar**. O estado deve voltar a **Parado**.

A tentativa do passo 6 usa o comando fixo `g5_missions_list`. Com o cache de grant vazio, o Rust recusa antes de uma nova ida ao FastAPI e mostra a frase acima. A negativa correspondente do FastAPI, com o mesmo texto, já foi exercida pelo supervisor de produção em `g5_missions_list_server_probe_for_integration_test`. As duas camadas precisam constar da evidência: a frase na WebView e a referência ao teste do supervisor.

## Launcher

O teste de supervisor, compilado sem `cfg(test)`, inicia o FastAPI real pelo `serve.py` do virtualenv, prova o UDS, lê a missão sintética, revoga, recebe a negativa do servidor, faz STOP, EOF, crash e restart. O binário release também sobe como helper, chega a READY no protocolo 3 e é recolhido (`release_tauri_binary_is_spawned_and_reaped`).

Isso é marco local no checkout. Não é pacote distribuível: `helper_command` resolve `serve.py` por `CARGO_MANIFEST_DIR` e só repassa `JARVIS_LOCAL_PASSPHRASE` e `JARVIS_DATABASE_PATH` se já existirem no ambiente. Não há instalador, segredo em Keychain nem runner embutido.

## Comandos

| Comando | Resultado |
|---|---|
| `uv run pytest` das suítes nativas, de missões e `test_local_security.py` | 130 passaram, 45,02 s; aviso Starlette/httpx |
| `cargo test --features mac003-production-supervisor-test` | lib 83 passaram, 9 ignorados; integração do supervisor 1 passou, 4,44 s |
| `node --test tests/runtimeCommand.test.mjs` | 4 passaram |
| `npm run build` | `tsc` e Vite passaram |
| `npm run tauri -- build --no-bundle` | passou; binário release em 2m03s na repetição com o botão |
| `release_tauri_binary_is_spawned_and_reaped` | passou, 0,37 s |
| `cargo fmt --all -- --check` e `git diff --check` | passaram |
| `osascript` `UI elements enabled` | `false` |

Ignorados de propósito: stresses de MAC-001.2 e MAC-002.1, entrypoints de processo filho e o teste de release na suíte principal (executado depois, à parte, quando o binário existia).

## Limites

Não houve aceite formal. O smoke da janela continua dependente da execução manual acima. Distribuição, OAuth, dados reais e serviços externos continuam fora deste marco.
