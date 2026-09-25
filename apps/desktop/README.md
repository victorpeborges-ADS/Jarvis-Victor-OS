# JARVIS Desktop — scaffold Tauri 2 + React/Vite

**Frontend scaffold compilado para web. Binário nativo NÃO COMPILADO; `.app` NÃO GERADO.** `rustc` e `cargo` não estavam instalados/disponíveis no PATH e não foram instalados nesta sprint.

## Escopo deste scaffold

- Telas sintéticas Agora, Conversa e Missões, com conteúdo neutro e sem persistência.
- Sem execução de shell, plugins de abertura externa, atalhos globais, captura de tela, acessibilidade nativa ou conexão de conta.
- Vite e Tauri estão configurados para loopback. A CSP não permite carregar páginas de terceiros.
- O projeto é isolado do Next.js; nenhum componente do frontend web foi importado como se fosse SPA.

## Verificação local

`npm install` e `npm run build` neste diretório verificam somente o frontend React/Vite. Nesta sprint, `npm run build` passou; isso não compila nem testa Rust/Tauri.

Quando Rust e os pré-requisitos Tauri estiverem provisionados, rodar `npm run tauri dev` em ambiente local. Para produzir `.app`, verificar primeiro `npm run tauri build`, o destino/macOS atual e o comportamento do bundle. Não habilitar permissões ou automação sem revisão separada.

Scaffold criado por `create-tauri-app` oficial (template React + TypeScript). Referências: [criar projeto Tauri 2](https://v2.tauri.app/start/create-project/) e [pré-requisitos](https://v2.tauri.app/start/prerequisites/).
