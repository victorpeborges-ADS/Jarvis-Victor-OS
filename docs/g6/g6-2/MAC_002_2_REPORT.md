# MAC-002.2 — Correção exclusiva da reutilização CTR

## BASELINE e objetivo

- Branch nova: `feat/jarvis-g6-mac-002-2-ctr-fix`.
- Worktree: `/Users/vic/.codex/worktrees/jarvis-g6-mac-002-2-ctr-fix/Jarvis-Victor-OS`.
- Base auditada: `d898ea287338613ec4adb546dcd9952e400964a5`, branch preservada `feat/jarvis-g6-mac-002-2-aead-uds-remediation`.
- Base anterior `5dd976e94acff09316381e455d4bd5ac1543ce38` confirmada ancestral da base auditada. Worktree nova limpa antes das edições.
- Regras: AGENTS.md, RTK, Blueprint e PromptPack lidos. Nenhuma regra adicional em subdiretórios.
- Objetivo: corrigir exclusivamente o P1 de keystream AES-CTR, sem mudar controles G5, SQLite, migrations, bootstrap privado, proteção por PID ou UDS-only.

A auditoria independente demonstrou reutilização de blocos de contador entre mensagens multibloco consecutivas e recuperação de plaintext com outro plaintext conhecido. Não demonstrou captura desses ciphertexts pelo atacante same-UID após a proteção por PID, nem falsificação de HMAC. A proteção contra substituição de listener havia bloqueado as cinco operações com zero bytes enviados ao peer falso. Esse limite de evidência permanece explícito.

A especificação normativa é [MAC_002_2_ENCRYPTED_UDS.md](MAC_002_2_ENCRYPTED_UDS.md). O histórico anterior, incluindo testes e falhas da candidata v2, permanece no SHA auditado; seus resultados não são considerados prova da correção atual.

## DECISÕES e limites

Mantido Encrypt-then-MAC: não há adapter AEAD seguro e interoperável já implementado entre Rust e Python. Não foram adicionadas dependências nem alterados lockfiles.

O protocolo v3 usa `sequence_be64 || zero_be64` como nonce e contador inicial. Cada sequência reserva uma faixa de `2^64` contadores. Ciphertexts são limitados a 1232 bytes request (77 blocos) e 2055 bytes response (129 blocos). Os limites anteriores de corpos G5 e envelopes externos são preservados. Nunca há carry do contador de bloco para a sequência; incremento da sequência é checked, zero e metade baixa não zero são recusados, e sequência máxima não permite wrap. HMAC é validado antes de descriptografar; tamanho e nonce canônico também são verificados antes de chamar a cifra no opener.

A prova MAC-002 permanece, com domínio de versão v3. Versão/build/rota/framing/KDF/MAC estão alinhados em Rust e Python, sem fallback v2. O RuntimeManager utiliza a constante do transporte nos estados e logs. Gerações recebem capability nova e contexto de derivação próprio; direção e propósito permanecem separados. Nunca reiniciar sequência sob uma capability/contexto reutilizados. Cada pedido aceito produz no máximo uma resposta sob sua chave de response.

A implementação CommonCrypto usa explicitamente `kCCModeOptionCTR_BE=2`. Testes reais verificam progressão de blocos 0, 1, 77 e 128, inclusive sequências próximas de `u64::MAX`, e o cálculo formal de não sobreposição. O cálculo completo está na especificação.

## ARQUIVOS ALTERADOS

- `apps/api/native_runtime.py`: v3, partição/limites e replay monotônico.
- `apps/api/test_native_ctr_partition.py`: nova regressão de plaintext conhecido, intervalos, limites, counter real, tag/ciphertext alterados e nenhuma descriptografia em rejeições, inclusive MAC válido com nonce/tamanho inválidos.
- `apps/api/test_native_app_api.py`: codec v3 e fixture de replay.
- `apps/api/test_native_runtime_process.py`: codec de referência v3 e fluxo de processo.
- `apps/desktop/src-tauri/src/transport.rs`: contador v3, guards antes da cifra, CommonCrypto explícito e regressões/interoperabilidade.
- `apps/desktop/src-tauri/src/runtime_manager.rs`: constante de versão compartilhada e PID correto na fixture de integração de teste; controles G5 intactos.
- `docs/g6/g6-2/MAC_002_2_ENCRYPTED_UDS.md`: contrato v3 e prova de não sobreposição.
- `docs/g6/g6-2/MAC_002_2_REPORT.md`: este handoff.
- `docs/g6/g6-2/RUNTIME_AUTHENTICITY.md`, `docs/g6/g6-2/TRANSPORT_DECISION.md`, `docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md`: referências de versão/rota alinhadas, sem alteração dos DTOs ou controles G5.

## COMANDOS EXECUTADOS e TESTES

Comandos com prefixo `rtk`; API executada em `apps/api` e Cargo em `apps/desktop/src-tauri`, salvo uso explícito de `--directory`/`--manifest-path`.

| Comando | Resultado efetivamente observado |
|---|---|
| `git rev-parse`, `git merge-base --is-ancestor BASE_ANTERIOR SHA_AUDITADO`, `git status --short`, `git worktree list` | PASS: SHA, ancestralidade, worktrees e baseline confirmados |
| `git worktree add -b feat/jarvis-g6-mac-002-2-ctr-fix WORKTREE d898ea287338613ec4adb546dcd9952e400964a5` | PASS: criada no caminho solicitado, limpa |
| `uv sync --locked --python 3.12` | PASS: ambiente local fixado; lockfile preservado |
| `uv run --locked --python 3.12 pytest -q --tb=short test_native_ctr_partition.py` antes da correção | EXPECTED FAIL: recuperação de plaintext nas duas direções |
| `cargo test --locked --features mac003-production-supervisor-test consecutive_multiblock_messages_do_not_reuse_keystream -- --test-threads=1` antes da correção | EXPECTED FAIL: keystream repetido no CommonCrypto real |
| Probe final Python de known-plaintext contra arquivos v2 exportados de `git show d898ea2:...`, em `/tmp/jv-ctr-old-regression-*` | EXPECTED FAIL: duas direções. Shim apenas adicionou constantes de tamanho para coletar testes; não alterou cifra ou nonce. Exportação removida |
| `uv run --locked --python 3.12 pytest -q --tb=short test_native_ctr_partition.py test_native_app_api.py test_native_runtime_process.py` | PASS: 23; um aviso de depreciação Starlette/httpx |
| `cargo test --locked --features mac003-production-supervisor-test transport::tests -- --test-threads=1` | PASS final: 24; 3 ignorados (entrypoint subordinado e stresses). Inclui funções de produção request/response, guards e interoperabilidade |
| `cargo test --locked --features mac003-production-supervisor-test separate_managers_and_stale_generations_cannot_cross_authenticate -- --test-threads=1` | PASS: 1 |
| `cargo test --locked --features mac003-production-supervisor-test --test mac003_production_supervisor -- --nocapture` | PASS: 1; supervisor real/FastAPI, G5, listener substituído pós-prova recebe zero bytes, STOP/EOF/crash/restart/reap/UDS cleanup |
| `cargo test --locked --features mac003-production-supervisor-test -- --test-threads=1` | PASS após ajuste da fixture: 80 unitários, 9 ignorados, mais 1 integração de produção. Guards adicionais posteriores foram cobertos na repetição final focada |
| `cargo fmt --all -- --check`, `cargo build --locked`, `git diff --check` | PASS final |

A interoperabilidade é uma regressão Cargo dedicada: Rust sela com funções de produção, Python abre com funções de produção, verifica conteúdo público sintético, sela novamente e Rust abre a resposta Python. Ciphertext/tag são comparados byte a byte para request e response nos limites de tamanho. Material gerado e mensagens trafegam somente em pipes privados, nunca em arquivos/logs; asserções não exibem bytes. A jornada de integração também usa framing real e FastAPI pelo UDS.

## Falhas intermediárias e diagnóstico

- Primeira invocação `uv sync` na raiz não encontrou pyproject; corrigido para `apps/api`. Primeiras invocações Cargo na raiz sem manifest não encontraram Cargo.toml; corrigidas para o diretório do crate.
- A primeira regressão Python tentou construir o cliente de teste com `raw=None`; falhou em `raw.app`, sem testar a cifra. A fixture foi corrigida; depois houve as duas falhas criptográficas esperadas antes da correção.
- As falhas red/green anteriores não exibiram plaintext, chaves, ciphertexts ou tokens.
- A primeira suíte Rust completa encontrou 79 PASS, 1 FAIL e 9 ignorados: a fixture `rust_manager_uses_fastapi_g5_over_authenticated_uds` iniciava child real sem configurar seu PID esperado (o default cfg(test) é o PID do pai). A fixture agora faz `set_expected_peer_pid(child.id())`, como o launcher de produção. Não foi relaxada nenhuma verificação de peer. Repetição: 80 PASS e integração PASS.
- Uma checagem de formato apontou wrapping após importar a constante da versão; aplicado cargo fmt e check final PASS.

## CAPTURAS/DEMOS, cleanup e preservação

Sem capturas visuais: o smoke Tauri/WebView não foi executado nem fechado. Probes e testes usaram somente material gerado/sintético e bancos descartáveis, sem banco padrão ou dados reais.

Supervisor e fixtures confirmaram STOP/reap/cleanup. A checagem filtrada de `ps -axo pid,command` não encontrou processos `serve.py --desktop-runtime`; glob de sockets de runtime `.jv-*`, `mac003-production-supervisor-*` e `jv-mac003-*` em diretórios temporários encontrou zero sockets. A exportação v2 do probe foi removida. O banco sintético deixado pela falha intermediária da fixture foi removido somente do diretório identificado desta execução, validando nomes de arquivos antes de unlink/rmdir. Nenhuma worktree anterior foi removida.

Branch auditada continua em `d898ea287338613ec4adb546dcd9952e400964a5`; main em `bf575be1645578eebedd41cddd3463b75726776b`; checkout compartilhado em `e648e92467396ce67b75019858fbcd0ee5557042`, branch `feat/gate2.0-e-integracao-web-api`. Seus quatro arquivos não rastreados permanecem: `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md`, `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md`, `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md`, `package-lock.json`. Worktree antiga detached `bb6b78a` preservada. A nova branch recebe somente commit local, sem merge/push/tag/deploy.

## RISCOS RESIDUAIS, AUTORIZAÇÃO e PRÓXIMO GATE

A não sobreposição vale para o estado monotônico único por geração, os limites de tamanho, CTR big-endian e chaves separadas por geração/direção. Não cobre reutilização externa deliberada de capability/contexto/nonce, comprometimento de processo, root/admin, inspeção privilegiada de memória, kernel ou DoS local. Comprimentos/tráfego não são ocultados. Stress tests marcados ignore e smoke de release/WebView continuam fora da evidência executada; frontend lint/typecheck/build não foram executados nesta alteração exclusivamente nativa/API.

Nenhum aceite formal é declarado. Próximo gate: reauditoria independente do commit local desta branch. MAC-003 e smoke Tauri/WebView permanecem abertos. Merge, push, tag, deploy, conectores reais e dados pessoais/institucionais não estão autorizados por esta entrega.

## Hardening de ciclo de vida pós-reauditoria

Branch `feat/jarvis-g6-mac-002-2-replay-lifecycle-fix`, worktree `/Users/vic/.codex/worktrees/jarvis-g6-mac-002-2-replay-lifecycle-fix/Jarvis-Victor-OS`, derivada de `f05e19222ee6d3ae58769632c2cea2470f109f86`. Não muda o wire format v3, a partição CTR, os limites de 77/129 blocos, as chaves por geração e direção, UDS-only, PID, lockfiles, migrations, SQLite ou controles G5.

Dois P3 da reauditoria ficam corrigidos no código de produção:

- O servidor autentica o HMAC e valida o nonce canônico antes de reservar a sequência. A reserva é atômica e ocorre antes do AES-CTR. Replay de sequência já reservada não descriptografa nem despacha. Falha de HMAC, nonce não canônico e ciphertext acima do limite não consomem sequência. Uma mensagem autenticada e canônica consome a sequência mesmo quando o frame ou o dispatch falham depois.
- `deactivate` segura o mutex da capability durante toda a transição: marca inatividade, apaga o segredo e estaciona a sequência em `u64::MAX`. A sequência não volta a zero. Alocação e seal releem atividade e presença do segredo sob o mesmo mutex. O envio recusa sessão inativa antes de escrever no socket.

A regressão de plaintext conhecido agora compara todos os blocos da mensagem, inclusive o bloco parcial, nas duas direções. A construção antiga `prefixo || sequência` produz interseção e o v3 produz zero blocos em comum. As asserções comparam apenas contagens.

Evidência desta correção, executada na worktree nova:

| Comando | Resultado |
|---|---|
| `uv sync --locked --python 3.12` em `apps/api` | PASS; lockfile preservado |
| `uv run --locked --python 3.12 pytest -q --tb=short test_native_ctr_partition.py test_native_app_api.py test_native_runtime_process.py` | PASS: 26; um aviso de depreciação Starlette/httpx |
| `cargo fmt --all -- --check` e `git diff --check` | PASS |
| `cargo test --locked --features mac003-production-supervisor-test --lib transport::tests -- --test-threads=1` | PASS: 25; 3 ignorados (entrypoint subordinado e dois stresses MAC-002.1); 62 filtrados de outros módulos |
| `cargo test --locked --features mac003-production-supervisor-test --test mac003_production_supervisor -- --test-threads=1` | PASS: 1; supervisor real/FastAPI, G5, STOP/EOF/crash/restart |

Não houve falha intermediária nesta correção. A suíte completa do crate e os stresses ignorados não foram repetidos. O smoke Tauri/WebView não foi executado. Nenhum aceite formal é declarado. Próximo passo: reauditoria focada deste commit. Merge, push, tag e deploy continuam não autorizados.
