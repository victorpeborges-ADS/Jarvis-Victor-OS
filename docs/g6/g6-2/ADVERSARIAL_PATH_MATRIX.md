# MAC-002.1 — Matriz adversarial de paths

## Reproduções no baseline `20626ebad5d01c6a8eee1a0366859e0be88764fd`

| Achado | Observação capturada |
|---|---|
| P2-A — EOF do supervisor | `instance_id=53516-1790980702377363000-1`, child `pid=53517`, socket em `/var/folders/q6/3c9fm74977l7425bpd0195100000gn/T/.jv-b34b64cd866e53da052dc659ee39599c/runtime.sock`. Após readiness/ACK, fechar stdin e aguardar 500 ms deixou `state=Ready`, child vivo e transporte `Ready` (`elapsed_ms=526`). Cleanup explícito do harness matou/reapou o child após `shutdown_timeout`. |
| P2-B — parent substituído por symlink | O diretório de sessão `.jv-4e9729016f832b0dd2a18a21e8bf4d01` foi renomeado e o nome original apontou para `...-canary`; `session.revoke()` removeu o arquivo externo `runtime.sock` imediatamente (`canary_runtime_sock_survived=false`, `elapsed_ms=0`). |

## Canários

Cada prova candidata cria target externo com bytes conhecidos em `canary.txt`, `runtime.sock` e `nested/canary2`. Asserções comparam os bytes completos antes/depois; portanto demonstram preservação do conteúdo equivalente ao hash esperado. Nenhuma prova usa dados do produto.

## Matriz candidata

| Momento/tipo | Prova | Resultado esperado/observado |
|---|---|---|
| Antes do bind: symlink para diretório externo | `replacement_before_child_bind_fails_closed_without_ready_or_canary_deletion` | Child lê init, nota `dev`/`inode` diferente, sai 44; nenhum `READY`; canários intactos. |
| Antes do bind: arquivo, symlink para arquivo, symlink para diretório, diretório novo, socket falso | `startup_path_replacement_types_fail_closed_before_bind` | CWD não diretório falha no spawn; diretório/symlink para diretório com identidade diferente falha no init; nenhum `READY`; canários intactos. |
| Cleanup do parent com tipos substitutos | `cleanup_is_anchored_to_original_directory_across_replacement_matrix` | `file`, symlink para arquivo, symlink para diretório, diretório novo com arquivo `runtime.sock` e UDS falso não são seguidos; target externo intacto. |
| Depois do bind / antes do cleanup do parent | `cleanup_after_bind_and_renamed_parent_preserves_external_canaries` | Diretório legítimo renomeado; nome original vira symlink para canários; parent remove socket somente no handle original. |
| Antes do cleanup do child | `child_drop_after_parent_rename_preserves_external_canaries` | `Drop` do config do child usa o FD validado depois de rename/symlink; socket do diretório original some, canários sobrevivem. |
| Manager A contra Manager B | `separate_managers_and_stale_generations_cannot_cross_authenticate` | Cleanup de A não invalida B; prova B continua `READY`. |

## Ciclos

- `stress_path_substitution_200_rounds`: 200 substituições e cleanup, 0 canários removidos.
- `stress_child_startup_path_substitution_200_rounds`: 200 children, todos falham antes de READY; 0 child residual e 0 canários removidos.

Falha fechada/DoS local é possível. O runtime preserva o diretório vazio depois de remover o socket; a política está em [SAFE_CLEANUP_POLICY.md](SAFE_CLEANUP_POLICY.md). O path aleatório reduz colisões acidentais, mas não é autorização contra processo do mesmo UID.
