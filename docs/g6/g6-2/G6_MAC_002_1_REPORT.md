# JARVIS G6-MAC-002.1 — relatório de implementação

## Candidata

- Branch: `feat/jarvis-g6-mac-002-1-uds-lifecycle-2026-10-02`
- Base direta: `20626ebad5d01c6a8eee1a0366859e0be88764fd` (MAC-002 reprovada)
- Ancestralidade: confirmada com `git merge-base --is-ancestor`.
- MAC-001 e `main` aceitas (`00753c58b97c3103d428bc6a0a9351f97b6c050d`), refs anteriores e checkout principal foram preservados.
- Commits da candidata: ver a sequência convencional desta branch e o SHA completo entregue no handoff.

## Objetivo e resultado

Correção cirúrgica dos dois achados P2 da candidata MAC-002: EOF definitivo do canal de controle agora revoga a sessão e encerra o child; mutações do socket UDS passaram a ser relativas ao descritor do diretório da geração, sem seguir o nome mutável da sessão. O contrato do transporte UDS e a prova HMAC do MAC-002 foram mantidos.

**Resultado:** os dois achados foram reproduzidos no baseline e os probes de correção passaram. Nesta implementação local, testes, build desktop e build Tauri sem bundle passaram. Não foi feito merge, push, tag ou deploy.

## Reprodução no baseline

Baseline executado em worktree descartável destacada no SHA exato, antes das alterações. Captura de stdout relevante:

```text
P2-A instance_id=53516-1790980702377363000-1 child_pid=53517
socket=/var/folders/q6/3c9fm74977l7425bpd0195100000gn/T/.jv-b34b64cd866e53da052dc659ee39599c/runtime.sock
after closing supervisor stdin and waiting 500 ms: state=Ready child_alive=true transport=Ready elapsed_ms=526
exit_code=0 (harness completed its explicit bounded kill/reap cleanup)

P2-B session=.jv-4e9729016f832b0dd2a18a21e8bf4d01
session.revoke(): canary_runtime_sock_survived=false elapsed_ms=0
exit_code=0 (reproduction harness completed)
```

Os dois resultados estão registrados em [ADVERSARIAL_PATH_MATRIX.md](ADVERSARIAL_PATH_MATRIX.md). A reprodução P2-B renomeou o diretório legítimo, instalou symlink no nome original e confirmou a remoção do `runtime.sock` externo.

## Mudanças

- `runtime_manager.rs`: EOF vira `SupervisorLost`; STARTING falha sem readiness e READY para de servir, invalida capability, reporta `supervisor_lost`, fecha UDS e aguarda/recolhe o processo. STOP mantém exit code 0; EOF usa exit code diagnóstico 48. A resposta de uma requisição em andamento não pode ser escrita depois que a liveness do canal cai. READY do parent só é publicado depois que o ACK foi escrito.
- `transport.rs`: parent retém o handle e identidade `dev/inode` do diretório; inicia child nele. O init transmite identidade, não socket path. Child abre `.` e confere identidade antes do bind; bind relativo `runtime.sock` usa modo 0600 via `umask(0177)`. Parent e child removem a folha fixa com `unlinkat(dirfd, ...)`, ancorado ao diretório original. Nenhum unlink produtivo usa pathname mutável.
- EOF/STOP concorrentes e chamadas repetidas são idempotentes. Probes usam o `request_lock` já existente; a geração e estado são conferidos antes de publicar resultado.
- HTTP continua um subconjunto mínimo: uma conexão UDS nova por pedido, sem keepalive, pipeline, chunked ou proxy genérico; bytes extras são rejeitados.
- FFI manual limitado a `unlinkat` e `umask`, APIs Unix disponíveis no toolchain alvo. Nenhuma crate/dependência foi adicionada.
- O diretório vazio `.jv-*` é preservado após a remoção do socket. Sob incerteza, falha fechada e preserva o path.

## Segurança filesystem e canários

A operação de remoção recebe um FD de diretório já aberto e validado e um nome-leaf constante; o kernel resolve a entrada relativa àquele descritor. Uma troca posterior do parent pathname por symlink não redireciona `unlinkat` para o target externo. A identidade `dev/inode` é usada para validar startup; ela não é tratada como substituto de uma mutação ancorada por handle.

Canários sintéticos `canary.txt`, `runtime.sock` e `nested/canary2` foram comparados byte a byte antes/depois. A matriz cobre substituição antes do bind por arquivo, symlink para arquivo, symlink para diretório, diretório novo e socket falso; substituição após bind; rename do diretório original; cleanup do child e do parent; e isolamento entre Managers. Não houve remoção externa. Ver [UDS_FILESYSTEM_SAFETY.md](UDS_FILESYSTEM_SAFETY.md), [SAFE_CLEANUP_POLICY.md](SAFE_CLEANUP_POLICY.md) e [ADVERSARIAL_PATH_MATRIX.md](ADVERSARIAL_PATH_MATRIX.md).

Aleatoriedade do path só reduz colisões acidentais; não autoriza contra outro processo do mesmo UID. Autenticidade continua dependendo da capability de 256 bits e da prova HMAC com nonce fresco. Segredo não é passado em argv, environment, frontend ou logs.

## Evidências e comandos

Todos os comandos de shell foram executados com o wrapper `rtk`, conforme `/Users/vic/.codex/RTK.md`.

| Comando / probe | Resultado |
|---|---|
| `cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml -- --check` | PASS |
| `cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS |
| `cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml -- --test-threads=1` | PASS: 69 passed, 9 ignored, 0 failed |
| `npm ci --prefix apps/desktop` | PASS; lockfile existente; nenhuma dependência declarada alterada |
| `npm run build --prefix apps/desktop` | PASS: TypeScript e Vite |
| `node --test apps/desktop/tests/*.test.mjs` | PASS: 2 passed |
| `npm run tauri --prefix apps/desktop -- build --no-bundle` | PASS; build nativo local sem assinatura/notarização |
| `release_tauri_binary_is_spawned_and_reaped` | PASS; teste ignored invocado explicitamente |
| `stress_normal_transport_lifecycle_500_rounds` | PASS: 500 ciclos, 39,27 s |
| `stress_supervisor_eof_200_rounds` | PASS: 200 ciclos, 13,06 s |
| `stress_path_substitution_200_rounds` | PASS: 200 ciclos, 0,14 s |
| `stress_child_startup_path_substitution_200_rounds` | PASS após refatoração do harness: 200 children, 7,25 s |
| `stress_start_stop_race_1000_rounds` | PASS: 1.000 ciclos, 34,79 s |
| `pre_ready_exit_classification_1000_rounds` | PASS: 1.000 ciclos, 37,07 s |
| Testes EOF STARTING/READY/proof, EOF + STOP, perda abrupta do parent, framing, probes concorrentes e matriz de substituição | PASS; prova READY exige child sair em menos de 350 ms |
| `npm audit --prefix apps/desktop` | FAIL exit 1: um advisory HIGH em `source-map-js@1.2.1`, transitiva de `vite@8.3.1 → postcss@8.5.28`; lockfile inalterado |
| `npm ls source-map-js --prefix apps/desktop` | Vite → PostCSS → `source-map-js@1.2.1` |
| `lsof -nP -iTCP:3000 -iTCP:8000 -iTCP:1420 -sTCP:LISTEN` | exit 1 sem stdout: zero listener nas três portas |

Os dois entrypoints subprocessados ignored (`runtime_helper_entry`, `fake_runtime_process_entry`) são executados pelos testes controladores; os outros sete testes ignored foram invocados explicitamente, incluindo os seis stresses e o binário release. Ver [TEST_MATRIX.md](TEST_MATRIX.md) para o mapa de cenários.

Após as verificações finais: `ps` filtrado não encontrou processos `jarvis`/`desktop`; `lsof -U` não encontrou `runtime.sock` nem `.jv-*` abertos; busca no temp não encontrou `runtime.sock` ou diretório `.jv-*` residual de teste; não restou canário. `lsof` também confirmou zero listener nas portas TCP 3000, 8000 e 1420. O comando `git fsck --full` terminou com exit code 0 e listou objetos dangling, sem reportar erro de integridade. O checkout principal permaneceu na branch `feat/gate2.0-e-integracao-web-api` com seus quatro arquivos untracked intactos.

## G5 e higiene

Diff zero em `apps/api`, `migrations`, `docs/adr/010-local-review-trust-boundary.md` e lockfiles. Nenhuma alteração em contratos SQLite/proveniência. `ADR-011` recebeu somente a emenda de transporte MAC-002.1. Nenhum TCP foi iniciado. Checkout principal, refs anteriores e arquivos untracked foram preservados. A branch fica em worktree exclusiva derivada exatamente do SHA congelado.

## Riscos residuais

- `npm audit` reporta um advisory HIGH herdado pela árvore travada em `source-map-js`; é ferramenta transitiva do build e requer atualização de dependência separada. Nenhum lockfile foi editado.
- Diretórios de sessão vazios permanecem no temp após uso normal. Esta é a escolha fail-safe; não há tentativa de `remove_dir` em pathname mutável na produção.
- Como o contrato é local e same-UID, processo host com o mesmo usuário pode causar negação de serviço e observar/substituir paths; a correção impede traversal/remoção externa no cleanup e preserva autenticação HMAC. Não é garantia contra administrador/root, SIGKILL do kernel ou falhas do sistema operacional.
- O aceite MAC-002.1 não cobre integração com FastAPI G5, dados pessoais, rede, multiworker, assinatura, notarização ou MAC-003.

## Próximo gate

Auditoria independente da candidata MAC-002.1, incluindo revisão de `unlinkat`/ownership e execução dos comandos documentados. MAC-003 segue pendente e não foi iniciada.
