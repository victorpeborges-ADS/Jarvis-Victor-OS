# Retomada — JARVIS G6-MAC-002.1

> Estado: candidata aceita após auditoria independente final e integrada localmente à `main` por fast-forward. Consulte [ACEITE_G6_MAC_002.md](ACEITE_G6_MAC_002.md) para o registro formal, limites e advisory separado.

## Escopo

Esta branch fecha apenas a perda de supervisor e a segurança filesystem do lifecycle UDS local. A base exata é `20626ebad5d01c6a8eee1a0366859e0be88764fd`; a branch é `feat/jarvis-g6-mac-002-1-uds-lifecycle-2026-10-02`. Não inicia MAC-003 nem altera G5 ou ADR-010.

## Contratos implementados

- EOF definitivo do pipe de controle é `SupervisorLost`: aborta STARTING sem readiness ou desliga READY, fecha/revoga o transporte, invalida capability e termina o child sem reinício. STOP é evento distinto, com encerramento normal.
- O socket é criado e removido relativamente ao FD do diretório da geração. Startup valida `dev/inode`; cleanup não usa pathname mutável. Em dúvida, falha fechada e preserva artefatos externos.
- O diretório de sessão vazio fica no temp após o uso normal. Isso é deliberado para não tentar remover diretório via pathname que pode ser substituído.
- HTTP sobre UDS continua mínimo: uma conexão por request, sem pipeline/chunked/proxy.
- `request_lock` serializa probes; somente resultado válido da geração ainda ativa é publicado.

## Verificação já executada

`cargo fmt --check`, `cargo check --locked`, suíte Rust (69 aprovados, 9 ignored), build web, testes Node, build Tauri sem bundle, binário release real, seis stresses ignored, provas de EOF/path/framing e ausência de listeners TCP nas portas 3000/8000/1420 passaram. `npm audit` retornou exit 1 por advisory HIGH transitivo em `source-map-js@1.2.1`; nenhuma dependência ou lockfile foi alterada. Detalhes e capturas baseline estão em [G6_MAC_002_1_REPORT.md](G6_MAC_002_1_REPORT.md).

## Continuação

SHA funcional aceito: `c64ee0ae02274bc8ba6041edae043450b9313b6d`. A árvore integrada coincide com a candidata auditada; a verificação da auditoria não foi repetida após o fast-forward. A integração local não autoriza push, tag, deploy, FastAPI G5, alteração de ADR-010, OAuth, rede ou MAC-003. Diretórios vazios deixados pelo runtime são resíduos seguros documentados, não devem ser removidos agressivamente.
