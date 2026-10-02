# JARVIS Desktop — Tauri 2 + React/Vite experimental

O diretório continua experimental. O frontend web e o executável Tauri sem bundle foram compilados no subgate G6-MAC-001. O `.app` não foi gerado, assinado ou aceito para distribuição.

## Escopo deste scaffold

- Telas sintéticas Agora, Conversa e Missões, com conteúdo neutro e sem persistência.
- Sem execução de shell, plugins de abertura externa, atalhos globais, captura de tela, acessibilidade nativa ou conexão de conta.
- A seção “Runtime local” controla somente um helper sintético filho do próprio executável. A MAC-002 acrescenta autenticidade de instância por UDS e prova HMAC; não inicia a API G5 e não lê SQLite.
- Vite de desenvolvimento permanece em loopback. O runtime não abre TCP: Tauri IPC chama rotas nativas fixas sobre um UDS privado por geração. A CSP permanece restrita a IPC.
- O projeto é isolado do Next.js; nenhum componente do frontend web foi importado como se fosse SPA.

## Verificação local

`npm run build` verifica o frontend React/Vite. `npm run tauri -- build --no-bundle` compila o executável nativo, mas não produz `.app`. A matriz e os limites do lifecycle estão em [`docs/g6/g6-1/G6_MAC_001_REPORT.md`](../../docs/g6/g6-1/G6_MAC_001_REPORT.md).

Missões, Aprovações e Configurações continuam sem integração à API. O helper e seus comandos não recebem endpoint, segredo, URL ou cabeçalhos da interface. A decisão, ameaça e handoff para FastAPI estão em [`docs/g6/g6-2`](../../docs/g6/g6-2/G6_MAC_002_REPORT.md); MAC-003 ainda exige autorização e execução própria.

Scaffold criado por `create-tauri-app` oficial (template React + TypeScript). Referências: [criar projeto Tauri 2](https://v2.tauri.app/start/create-project/) e [pré-requisitos](https://v2.tauri.app/start/prerequisites/).
