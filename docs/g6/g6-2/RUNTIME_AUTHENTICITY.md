# G6-MAC-002 — Autenticidade da instância

## Evidência que não autentica

- PID é informativo e pode ser reutilizado.
- Porta ou path identifica localização, não processo.
- `runtime_instance_id` e build anunciados pelo socket são afirmações do peer.
- `200 OK`, `/health` e versão compatível não provam ownership.

## Capacidade e prova

1. Antes do spawn, Runtime Manager gera 32 bytes usando `SecRandomCopyBytes` do macOS e cria um UDS em diretório aleatório exclusivo da geração, modo 0700.
2. O helper recebe ID, capacidade e path por um registro limitado escrito no `stdin` privado do processo supervisionado. Nenhum desses segredos é argumento, variável de ambiente, URL, log ou valor de resposta IPC.
3. O helper vincula o UDS com permissão 0600 e só anuncia readiness depois do bind.
4. Depois do ACK de readiness, o native client consulta `health` e `version`; ambas são evidências informativas.
5. O native client gera nonce novo de 32 bytes com o CSPRNG do macOS e envia o nonce em corpo de `POST /v1/instance-proof`.
6. O helper retorna protocol, runtime kind, instance ID, build, resultado sintético e HMAC-SHA-256. A mensagem assinada tem domínio `jarvis-local-transport-proof-v1`, versão, tipo, ID, build, nonce e resultado `pong:<instance_id>`.
7. Rust valida campos, compatibilidade, identidade esperada e HMAC usando CommonCrypto. Um resultado só marca `TransportState.READY` depois disso.

Health e version são consultas independentes e não autenticam. O resultado `pong` está no mesmo response autenticado pelo HMAC; não há pedido posterior sem prova que possa ser substituído por um peer falso.

## Isolamento da WebView e managers

O objeto `TransportSession` e a capacidade ficam na camada Rust. IPC retorna somente estado, ID, tipo UDS, versão e categoria de erro. Uma Manager B tem chave e path independentes; resposta de B não valida com a chave de A, mesmo que ambas estejam `READY` e anunciem a mesma versão.

Cada sessão captura path, capacidade e ID de sua geração. No stop, a capacidade é desativada imediatamente para impedir novos probes; se o child ainda está iniciando, o diretório permanece disponível até o child processar STOP/reap. Depois do reap, path e diretório são removidos. Uma sessão A retida por chamada pendente não consulta o estado atual para trocar para B. Depois do stop, a própria sessão A retorna `generation_inactive`.

## Criptografia e memória

Não há algoritmo implementado no repositório. Entropia vem de `SecRandomCopyBytes`; HMAC usa `CCHmac` do sistema Apple/CommonCrypto com SHA-256. A suíte valida CCHmac com vetor conhecido. Não foi incluída dependência Rust nem npm.

O zeroing em memória é best effort do código e não é garantia contra dump, depurador, root/admin ou comprometimento do processo. A fronteira ADR-010 e o escopo local sintético permanecem intactos.
