# ADR-011 — Transporte local e autenticidade do runtime desktop

- **Status:** aceito para a candidata G6-MAC-002
- **Data:** 2026-10-02
- **Escopo:** somente o cliente desktop Tauri e seu runtime sintético supervisionado
- **Baseline:** `00753c58b97c3103d428bc6a0a9351f97b6c050d`

## Contexto

A MAC-001 supervisiona um processo filho e confirma sua prontidão por `stdin/stdout`. O passo seguinte precisa permitir pedidos tipados sem dar à WebView autoridade sobre endpoint, segredo, URL ou cabeçalhos. A versão futura do servidor poderá ser FastAPI, mas esta decisão não autoriza importar ou executar a API G5.

Health, PID, porta e `runtime_instance_id` anunciados pelo endpoint são metadados, não autenticadores. O runtime precisa provar posse de uma capacidade aleatória transmitida ao processo filho pelo pipe privado que o supervisor já controla.

## Alternativas

| Opção | Autenticidade e exposição | Origin, Host, CORS, CSRF e CSP | Ciclo de vida e descoberta | FastAPI futura | Decisão |
|---|---|---|---|---|---|
| A. WebView → HTTP loopback | Exige listener TCP e torna o runtime acessível a outros processos locais. Um segredo não deve ir para JavaScript. Porta fixa colide; porta efêmera exige descoberta. | O browser envia `Origin`; `Host` precisa de validação; CORS é necessário para origens diferentes e não autentica. Requisições mutáveis exigem defesa CSRF. CSP teria de permitir HTTP local. IPv4 e IPv6 precisam de binds explícitos. | A WebView não pode escolher nem procurar o endpoint, mas precisa receber dados suficientes para chamá-lo. Corridas de restart podem reapontar chamadas. | Natural para Uvicorn, com maior superfície browser/TCP. | Rejeitada. |
| B. WebView → Tauri IPC → HTTP loopback | Mantém segredo e seleção de endpoint no Rust, mas conserva um listener TCP local, colisões e acesso por clientes locais. Exige prova por capacidade em cada instância. | Origin/CORS/CSRF deixam de governar a chamada Rust, mas Host e defesa a clientes locais continuam relevantes. CSP não precisa liberar o runtime se a WebView usa IPC. IPv4 e IPv6 continuam sendo escolhas de bind separadas. | O Runtime Manager guarda host/porta por geração; nenhuma porta fixa, varredura ou fallback sequencial. | Natural para Uvicorn. | Rejeitada em favor de não abrir listener TCP. |
| C. WebView → Tauri IPC → HTTP/1.1 sobre UDS | Sem porta TCP, colisão de porta ou exposição LAN. O path fica em diretório privado por geração; HMAC impede que um socket falso se autentique. | Origin não é enviado por uma conexão nativa UDS; o servidor recusa `Origin`. Não há CORS. CSRF de browser não rege a chamada, e HMAC continua necessário contra outros clientes locais. `Host` é fixo em `jarvis.local` e validado. CSP permanece restrita a IPC. | Parent cria path aleatório, o associa à geração, envia path e capacidade somente por `stdin`; não há scanning nem endpoint vindo da UI. Revogação remove socket, diretório e capacidade. | Uvicorn suporta UDS. MAC-003 precisará adaptar seu runner loopback atual para receber o path privado e servir o mesmo contrato HTTP em UDS. | **Selecionada.** |
| D. WebView → Tauri IPC → RPC por `stdin/stdout` | Canal naturalmente vinculado aos pipes do child, sem endpoint ou segredo, e forte isolamento entre managers. | Sem Origin, CORS, CSRF ou mudança de CSP. | O multiplexamento de mensagens de produto, readiness e stop precisa de framing, IDs de pedido, concorrência e limites de buffer. | FastAPI não serve HTTP em stdio; exigiria um adaptador adicional e mudaria a operação do runtime. | Alternativa segura, com maior custo de compatibilidade. |

## Decisão

Selecionar C. Tauri expõe somente comandos tipados de estado e probe. Rust conecta ao único UDS criado para a geração atual. O helper recebe uma capacidade aleatória de 256 bits pelo pipe privado, nunca por argv, ambiente, URL, logs ou IPC da WebView. Rust e helper usam `SecRandomCopyBytes` (Security.framework) e `CCHmac`/SHA-256 do CommonCrypto/libSystem; nenhuma crate ou pacote foi adicionado.

O handshake consulta health e versão, depois faz um pedido `POST /v1/instance-proof` com nonce aleatório. A resposta inclui a operação sintética `pong:<instance_id>`; HMAC-SHA-256 cobre domínio, versão do protocolo, tipo/build, ID, nonce e resultado. Isso liga a prova e o pedido ao mesmo response. Somente depois da comparação a sessão passa a `READY`.

O protocolo implementa um subconjunto fechado de HTTP/1.1 com rotas fixas, `Host: jarvis.local`, `Content-Length`, limites e prazos. Não aceita proxy genérico, rota fornecida pelo frontend, `Transfer-Encoding`, `Origin` nem cabeçalhos de autorização.

## Consequências e limites

- `RuntimeState.READY` continua significando apenas prontidão do processo. `TransportState.READY` exige handshake de versão e prova HMAC.
- Cada geração tem path e capacidade novos. Uma chamada retém a sessão capturada e nunca troca automaticamente para a geração posterior.
- HMAC não protege contra administrador, processo que compromete o próprio cliente ou leitura de memória do host. MAC-002 não promete isolamento entre processos do mesmo usuário contra inspeção privilegiada.
- UDS e permissões 0700/0600 reduzem a superfície entre usuários; HMAC é a autenticação efetiva contra um socket local falso do mesmo usuário.
- O runtime sintético não inicia FastAPI, G5, SQLite, migrações nem listener TCP.

## Referências primárias

- [Apple — SecRandomCopyBytes](https://developer.apple.com/documentation/security/secrandomcopybytes%28_%3A_%3A_%3A%29?changes=l_9&language=objc)
- [Apple — CCHmac](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/CCHmac.3cc.html)
- [Rust — Unix domain sockets](https://doc.rust-lang.org/std/os/unix/net/index.html)
- [Uvicorn — configurações, incluindo UDS](https://www.uvicorn.org/settings/)
- [Uvicorn — deployment](https://www.uvicorn.org/deployment/)

## Aditamento MAC-002.1 — EOF do supervisor e cleanup UDS (2026-10-06)

Este aditamento corrige o lifecycle local sem alterar a escolha UDS, o contrato criptográfico nem ADR-010.

- O registro enviado pelo parent agora contém `instance_id`, capacidade de 256 bits e `dev`/`inode` da sessão; não contém o path do socket. O child inicia com o diretório da geração como CWD, abre `.`, verifica sua identidade e binda `runtime.sock` relativamente a esse diretório com modo 0600.
- O parent conserva um handle do diretório original. Child e parent removem somente a folha fixa `runtime.sock` com `unlinkat` relativamente ao handle. Renomear o diretório ou substituir o nome por symlink não redireciona cleanup ao target externo. O check do nome é usado para falhar readiness; a mutação do socket não depende de `check → unlink(path)`.
- EOF definitivo no canal herdado de controle revoga ownership. Antes de readiness, startup aborta sem `READY`; depois do ACK, o child deixa de aceitar pedidos, suprime respostas pendentes após a observação de EOF, remove o socket ancorado ao handle e sai com motivo `supervisor_lost`. O parent revoga a capacidade e reap o processo. STOP continua sendo encerramento normal distinto.
- O diretório privado vazio é preservado após cleanup porque remover o próprio diretório exigiria resolver um nome mutável sem uma primitiva segura disponível nesta implementação. É um artefato limitado; gerações futuras usam novos nomes aleatórios. Diretórios desconhecidos ou substituições são preservados.
- Nenhuma crate/dependência foi adicionada. O código usa wrappers FFI pequenos para `unlinkat` e `umask` do sistema, além de `File`/`MetadataExt` da biblioteca padrão.

O path aleatório reduz colisões acidentais; não é controle de autorização contra processos do mesmo UID. HMAC continua sendo a autenticação do runtime sintético. O escopo local, sintético e monoprocesso permanece inalterado.
