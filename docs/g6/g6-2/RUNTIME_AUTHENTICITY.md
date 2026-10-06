# G6-MAC-002 — Autenticidade da instância

## Evidência que não autentica

- PID é informativo e pode ser reutilizado.
- Porta ou path identifica localização, não processo.
- `runtime_instance_id` e build anunciados pelo socket são afirmações do peer.
- `200 OK`, `/health` e versão compatível não provam ownership.

## Capacidade e prova

1. Antes do spawn, Runtime Manager gera 32 bytes usando `SecRandomCopyBytes` do macOS, cria diretório aleatório exclusivo da geração com modo 0700 e mantém aberto um handle para ele. Registra `dev`/`inode` do handle e do nome criado.
2. O processo recebe ID, capacidade e identidade do diretório por registro limitado no `stdin` privado. O path não é escrito nesse registro, em argv, ambiente, log nem IPC da WebView. O child inicia no diretório preparado pelo supervisor, abre `.` e compara sua identidade com `dev`/`inode` antes do bind.
3. O helper vincula `runtime.sock` relativamente ao diretório aberto, com `umask(0177)` para criar o socket em modo 0600, e só anuncia readiness depois do bind. O supervisor verifica que o nome da sessão ainda aponta para o handle original antes de aceitar readiness.
4. Depois do ACK de readiness, o native client consulta `health` e `version`; ambas são evidências informativas.
5. O native client gera nonce novo de 32 bytes com o CSPRNG do macOS e envia o nonce em corpo de `POST /v1/instance-proof`.
6. O helper retorna protocol, runtime kind, instance ID, build, resultado sintético e HMAC-SHA-256. A mensagem assinada tem domínio `jarvis-local-transport-proof-v1`, versão, tipo, ID, build, nonce e resultado `pong:<instance_id>`.
7. Rust valida campos, compatibilidade, identidade esperada e HMAC usando CommonCrypto. Um resultado só marca `TransportState.READY` depois disso.

Health e version são consultas independentes e não autenticam. O resultado `pong` está no mesmo response autenticado pelo HMAC; não há pedido posterior sem prova que possa ser substituído por um peer falso.

## Isolamento da WebView e managers

O objeto `TransportSession` e a capacidade ficam na camada Rust. IPC retorna somente estado, ID, tipo UDS, versão e categoria de erro. Uma Manager B tem chave e path independentes; resposta de B não valida com a chave de A, mesmo que ambas estejam `READY` e anunciem a mesma versão.

Cada sessão captura handle do diretório, path de conexão, capacidade e ID de sua geração. No stop ou perda do pipe de controle, a capacidade é desativada para impedir novos probes. Cleanup do socket usa `unlinkat` relativo ao handle do diretório, tanto no parent quanto no child. Renomear o diretório ou substituir o nome original por symlink não redireciona essa operação. O diretório vazio é preservado no runtime normal porque a biblioteca padrão não fornece remoção segura do próprio diretório pelo handle; sob path incerto, o sistema preserva qualquer artefato em vez de seguir outro caminho. Uma sessão A retida por chamada pendente não consulta o estado atual para trocar para B. Depois da revogação, a própria sessão A retorna `generation_inactive`.

O canal stdin é ownership: EOF durante startup aborta readiness; EOF depois de ACK encerra o child, fecha o serviço UDS e invalida a capacidade. O shutdown por EOF usa diagnóstico `supervisor_lost`, separado do STOP normal. Uma resposta de probe que termine depois de stop/EOF não repõe `READY`.

## Criptografia e memória

Não há algoritmo implementado no repositório. Entropia vem de `SecRandomCopyBytes`; HMAC usa `CCHmac` do sistema Apple/CommonCrypto com SHA-256. A suíte valida CCHmac com vetor conhecido. Não foi incluída dependência Rust nem npm.

O zeroing em memória é best effort do código e não é garantia contra dump, depurador, root/admin ou comprometimento do processo. A fronteira ADR-010 e o escopo local sintético permanecem intactos.
