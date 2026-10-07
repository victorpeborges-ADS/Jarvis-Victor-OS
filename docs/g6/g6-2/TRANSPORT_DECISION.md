# G6-MAC-002 — Decisão de transporte

**Escolha:** WebView → Tauri IPC → cliente Rust limitado → HTTP/1.1 em UDS → runtime sintético. A decisão detalhada, incluindo opções A–D, está no [ADR-011](../../adr/011-local-desktop-runtime-transport.md).

**Emenda MAC-002.2:** a prova HMAC do handshake autentica o runtime para o cliente, mas não protege uma requisição posterior se o pathname UDS for trocado. Antes de enviar qualquer byte por uma conexão, Rust agora valida `LOCAL_PEERPID` contra o child supervisionado. As operações G5 são envelopadas em AES-256-CTR + HMAC-SHA-256 por direção e por geração. A rota externa única `/v2/secure` falha fechada em versões incompatíveis; o protocolo está descrito em [MAC_002_2_ENCRYPTED_UDS.md](MAC_002_2_ENCRYPTED_UDS.md).

| Pergunta | Resposta | Motivo |
|---|---|---|
| TRANSPORT SELECTED | Tauri IPC → UDS HTTP | Compatibiliza canal nativo sem TCP com HTTP/1.1 que Uvicorn pode servir futuramente. |
| WEBVIEW TALKS DIRECTLY TO RUNTIME | NO | Somente comandos Tauri tipados alcançam Runtime Manager. |
| TCP LISTENER | NO | Cliente e helper usam `AF_UNIX`; não abrem listener IPv4 ou IPv6. |
| UDS | YES | Socket por geração em diretório privado, removido em stop/crash. |
| RUNTIME SECRET EXPOSED TO WEBVIEW | NO | Capacidade vive somente em Rust e no processo filho. |
| CORS REQUIRED | NO | WebView não faz HTTP ao runtime. O helper não instala middleware CORS. |
| CSRF REQUIRED ON INTERNAL RUNTIME CHANNEL | NO | Não há requisição browser-originated ao canal interno. Cada operação local exige envelope autenticado e cifrado; a WebView não recebe a capability. |
| CSP CHANGE REQUIRED | NO | A CSP existente já permite Tauri IPC e não precisa de HTTP/UDS. |

## Auditoria do stack presente

- `apps/desktop/src` não chama `fetch` nem recebe endpoint, porta ou cabeçalho. O código usa `@tauri-apps/api/core` e nomes de comandos fixos.
- `apps/desktop/src-tauri/src/lib.rs` registra comandos explícitos. A capability `default` concede `core:default`; não há plugin HTTP.
- `apps/desktop/src-tauri/tauri.conf.json` mantém `connect-src ipc: http://ipc.localhost`. `127.0.0.1:1420` é somente o Vite de desenvolvimento, não o runtime.
- `apps/web/lib/local-api.ts` pertence à aplicação web separada. Ela deriva ou aceita `NEXT_PUBLIC_JARVIS_API_URL`, valida loopback e usa `fetch` com credenciais locais; o default é porta 8000. Essa integração não é usada pelo cliente macOS.
- `apps/api/serve.py` é o runner oficial existente: `uvicorn.run` com bind default `127.0.0.1:8000`, sem proxy headers. `apps/api/loopback.py` limita binds e origens de browser a loopback; `main.py` instala CORS para origens explícitas, com credenciais e header CSRF. Não foi importado, executado ou alterado.

## TCP, IPv4 e IPv6

Uma alternativa TCP precisaria bindar `127.0.0.1:0` e obter a porta efêmera diretamente do socket criado pelo parent. Isso evita colisão e LAN, mas mantém um endpoint local acessível a outros processos. `::1` não é consequência de um bind `127.0.0.1`; dual stack exigiria configuração e validação explícitas. A escolha UDS elimina essa classe de configuração. As portas 3000 e 8000 ficam fora do caminho MAC-002.

## Host, Origin, CORS e CSRF

O cliente nativo envia `Host: jarvis.local`; o helper valida esse valor fixo e recusa qualquer `Origin`. O framing HTTP leva health/version/proof de controle e um envelope opaco para operações; G5 só é despachado depois da autenticação do envelope. Não há CORS. A prova de handshake autentica o runtime para Rust; o envelope autentica cada solicitação para o servidor e cada resposta para Rust, e também cifra ambos os sentidos.

## CSP e superfície Tauri

Sem mudança na CSP. A WebView não pode escolher host, porta, path, método, rota, executável, secret ou raw headers. Os únicos comandos novos são `runtime_transport_status` e `runtime_transport_probe`; o probe não recebe argumentos e só executa as três rotas sintéticas fixas.
