# G6-MAC-002 — Relatório da candidata

## Identificação

- Branch: `feat/jarvis-g6-mac-002-local-transport-2026-10-02`
- Worktree: `/private/tmp/jarvis-g6-mac002-local-transport-20261002`
- Baseline exata: `00753c58b97c3103d428bc6a0a9351f97b6c050d` (`main` limpa no início)
- Commit de implementação: `2b35c32c389fbd450ce70616e7668d1e964bbca9`
- Commit de correção de corrida: `f6a906ea562a9cd51d8a0e6995c506fa8b4ffc22`
- Candidata de código validada: `f6a906ea562a9cd51d8a0e6995c506fa8b4ffc22`; o SHA do commit documental que fecha a branch é informado no handoff final.
- Decisão: UDS HTTP privado por geração; ADR-011.

## Resultado técnico

O cliente macOS fala somente com comandos Tauri tipados. Runtime Manager inicia child sintético com pipes herdados, cria diretório UDS por geração, entrega a capacidade por stdin e guarda endpoint/chave exclusivamente em Rust. Child só declara readiness depois do bind UDS. A camada de transporte executa health e version separadamente, valida HMAC-SHA-256 com nonce CSPRNG sobre identidade, versão e resultado do probe e só então publica `READY`.

Não foi adicionado listener TCP nem dependência. Nenhuma chamada usa portas 3000 ou 8000. G5, `apps/api`, migrations e ADR-010 não foram alterados nem executados.

## Opções avaliadas

A WebView falando loopback diretamente exigiria superfície browser, CORS/Origin e defesa CSRF. Um proxy Rust sobre loopback esconderia o segredo do browser, mas manteria TCP/portas e acesso local. UDS elimina listener TCP; HTTP nele preserva compatibilidade futura com Uvicorn. RPC stdio seria ainda mais simples para autenticar ownership, mas exigiria adaptar FastAPI/stdio e multiplexar lifecycle e solicitações. Ver comparação completa em [TRANSPORT_DECISION.md](TRANSPORT_DECISION.md).

## Decisões explícitas

| Pergunta | Decisão | Motivo |
|---|---|---|
| WebView fala diretamente com o runtime? | NÃO | A WebView usa somente comandos Tauri tipados. |
| Listener TCP? | NÃO | O canal nativo usa UDS privado por geração. |
| UDS? | SIM | Evita portas, colisões, exposição LAN e descoberta por scanning. |
| Segredo do runtime exposto à WebView? | NÃO | A capacidade fica em Rust e chega ao child por stdin herdado. |
| CORS requerido? | NÃO | O browser não envia HTTP ao runtime interno. |
| CSRF requerido no canal interno? | NÃO | Não há endpoint interno acionável por requisição browser-originated; comandos IPC são tipados e limitados. Outros processos locais ainda precisam da prova HMAC. |
| Mudança de CSP requerida? | NÃO | `connect-src` permanece sem ampliação para HTTP local. |

HTTP interno exige exatamente `Host: jarvis.local`; Origin é rejeitado. Essa validação reduz ambiguidades do protocolo e não é tratada como autenticação.

## Autenticidade e lifecycle

PID, health, porta, versão e ID anunciado não autenticam. Secret aleatório de 256 bits via Security.framework e HMAC CommonCrypto são mecanismo do sistema Apple já disponível. O secret passa somente pelo stdin herdado e não aparece em argv/env/log/URL/frontend. Nonce de 256 bits evita replay; o resultado sintético é coberto pela mesma prova. Paths e capabilities são distintos por geração/Manager. Sessões stale são revogadas e não podem migrar para uma sessão nova.

Runtime e transporte usam estados separados. Readiness não publica autenticação. Timeouts são 350 ms para connect UDS, 900 ms por troca client, 500 ms para requisição no helper; limites de cabeçalho/corpo constam em [TRANSPORT_STATE_MACHINE.md](TRANSPORT_STATE_MACHINE.md).

## Validação

Preencher esta tabela com os resultados observados ao fechar a candidata:

| Validação | Resultado |
|---|---|
| `npm ci --prefix apps/desktop` | PASS; 27 pacotes já travados instalados, lockfile inalterado, 0 vulnerabilidades reportadas. |
| `npm run build --prefix apps/desktop` | PASS; `tsc` e Vite concluíram. |
| `node --test apps/desktop/tests/*.test.mjs` | PASS; 2 aprovados, 0 falhos. |
| `cargo fmt --check --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS. |
| `cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS; lockfile respeitado, sem dependência adicionada. |
| `cargo test --locked --manifest-path apps/desktop/src-tauri/Cargo.toml` | PASS; 55 aprovados, 0 falhos, 5 ignorados. |
| Probe de fake runtime separado | PASS, executado explicitamente: `transport::tests::fake_health_and_version_process_without_capability_is_rejected` (1 aprovado, 0 falhos); serve health/version sem capacidade e é recusado na prova. |
| `npm run tauri --prefix apps/desktop -- build --no-bundle` | PASS; executável macOS de release gerado sem bundle. |
| Probe do binário Tauri release real | PASS, repetido após a correção; `release_tauri_binary_is_spawned_and_reaped` autenticou UDS/protocolo e encerrou/reapou child (1 aprovado, 0 falhos). |
| Probe contra resultado tardio após invalidação no stop | PASS; a guarda exige estado `ProvingInstance`, mantendo `Disconnected` após resultado atrasado. Incluído na suíte Rust completa. |
| Cleanup de child, fake process, socket e diretório temporário | PASS; os testes assertam child/supervisor/sessão removidos e inspeção não encontrou diretórios `.jv-*` residuais nem processo Tauri/runtime da worktree. |
| Portas 3000, 8000 e 1420 livres | PASS; `lsof -nP -iTCP:<porta> -sTCP:LISTEN` sem saída (exit 1) para cada porta. |
| `git diff --check` | PASS. |
| `git fsck --full` | PASS, exit 0 após commits de código; foram listados objetos dangling preexistentes, sem erros missing/corrupt. Repetido após o commit documental no handoff final. |
| Diff G5 (`apps/api`, `docs/adr/010-local-review-trust-boundary.md`) | PASS; `git diff` vazio contra baseline. |

## Riscos residuais

Same-user malware com privilégio suficiente, administrador/root e processo comprometido estão fora da garantia, conforme ADR-010. UDS e permissões mitigam acesso entre usuários; HMAC autentica contra peers sem capacidade, não contra inspeção privilegiada de memória. A futura integração Uvicorn/UDS precisa implementação e teste em MAC-003; docs upstream sozinhas não comprovam a aplicação.

## Decisão de aceite

Este relatório registra evidência para auditoria independente. Não declara G5 formalmente aceito e não integra à `main`. MAC-003 deve trocar somente o child sintético por FastAPI supervisionado, mantendo comandos Tauri, contrato HTTP tipado, UDS gerado pelo parent, entrega de capacidade por canal herdado, HMAC de prova, timeouts, limites e estados; deve adaptar o runner oficial para bind ao socket Unix e repetir testes de readiness, prova, revogação, crash, cleanup e isolamento de geração sem abrir o banco G5 nesta etapa. Não há autorização para executar essa etapa, abrir SQLite, alterar ADR-010, usar rede, fazer merge, push, tag ou deploy.
