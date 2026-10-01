# JARVIS Desktop — Tauri 2 + React/Vite experimental

O diretório continua experimental. O frontend web e o executável Tauri sem bundle foram compilados no subgate G6-MAC-001. O `.app` não foi gerado, assinado ou aceito para distribuição.

## Escopo deste scaffold

- Telas sintéticas Agora, Conversa e Missões, com conteúdo neutro e sem persistência.
- Sem execução de shell, plugins de abertura externa, atalhos globais, captura de tela, acessibilidade nativa ou conexão de conta.
- A seção “Runtime local” controla somente um helper sintético filho do próprio executável. Ela prova lifecycle supervisionado; não inicia a API G5 e não lê SQLite.
- Vite e Tauri estão configurados para loopback. A CSP não permite carregar páginas de terceiros.
- O projeto é isolado do Next.js; nenhum componente do frontend web foi importado como se fosse SPA.

## Verificação local

`npm run build` verifica o frontend React/Vite. `npm run tauri -- build --no-bundle` compila o executável nativo, mas não produz `.app`. A matriz e os limites do lifecycle estão em [`docs/g6/g6-1/G6_MAC_001_REPORT.md`](../../docs/g6/g6-1/G6_MAC_001_REPORT.md).

Missões, Aprovações e Configurações continuam sem integração à API. O helper e seus comandos não recebem caminho de executável, argumentos ou variáveis de ambiente da interface. O próximo subgate precisa tratar endpoint, porta e origin antes de qualquer conexão autenticada.

Scaffold criado por `create-tauri-app` oficial (template React + TypeScript). Referências: [criar projeto Tauri 2](https://v2.tauri.app/start/create-project/) e [pré-requisitos](https://v2.tauri.app/start/prerequisites/).
