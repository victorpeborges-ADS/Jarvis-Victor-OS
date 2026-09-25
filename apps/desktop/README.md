# JARVIS Desktop — scaffold documental

Estado: **BLOCKED / NÃO COMPILADO**. Nenhum `.app` foi gerado.

## Direção proposta

PoC Tauri 2 + React/Vite isolada, consumindo somente os contratos em `../../contracts` e tokens/componentes que possam ser extraídos de `apps/web`. O primeiro shell exibirá Agora, Conversa e Missões sintéticas. Menu bar e atalho global ficam fora do primeiro build até haver uma prova de acessibilidade e permissões; não adicionar captura de tela nem execução de shell.

O app atual é Next.js e inclui rotas e providers de servidor; não será carregado como se fosse uma SPA estática sem antes provar export e isolamento. A implementação deve começar em um pacote Vite desktop independente, com dados DEMO sinalizados.

## Pré-requisitos e retomada

`rustc` e `cargo` não estavam disponíveis no PATH nesta sprint; não foram instalados. A documentação oficial Tauri 2 apresenta `npm create tauri-app@latest`, React/Vite e `npm run tauri dev`. Quando Rust e dependências Tauri 2 estiverem provisionados, executar esse scaffold em `apps/desktop`, apontar `frontendDist` para `../dist`, configurar Vite para ignorar `src-tauri/**`, implementar shell sintético, `cargo check`, testes web desktop e medir startup/RAM sem stress.

Nenhum comando do scaffold foi executado porque ele instala/cria um novo toolchain/dependências e não seria possível compilar neste host nesta janela. Nenhuma permissão nativa foi concedida.

Referência: [Tauri 2 — criar projeto](https://v2.tauri.app/start/create-project/) e [frontend Vite](https://v2.tauri.app/start/frontend/vite/).
