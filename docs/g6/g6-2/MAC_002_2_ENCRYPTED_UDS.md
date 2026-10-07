# MAC-002.2 — Canal UDS autenticado e cifrado

## Estado

Implementação candidata derivada de `5dd976e94acff09316381e455d4bd5ac1543ce38`, pendente de reauditoria independente. Este documento descreve a versão 2 do transporte local. Não declara aceite formal, integração à `main` nem fechamento do gate separado de smoke Tauri/WebView.

## Fronteiras

O transporte continua exclusivamente UDS por geração. A WebView chama comandos Tauri tipados; endpoint, capability, tokens e corpos de aplicação permanecem em Rust e no processo FastAPI supervisionado. O supervisor continua proprietário do spawn, stdin/EOF, STOP, crash, reap e cleanup.

O handshake de prontidão consulta health e version e prova a instância com um nonce novo e HMAC-SHA-256 no domínio `jarvis-local-transport-proof-v2`. Essa prova autentica o runtime para o cliente. Ela não é tratada como autenticação mútua de operações. Para cada conexão UDS, antes de escrever qualquer byte HTTP, Rust consulta `LOCAL_PEERPID` e exige o PID exato do child ainda supervisionado. Falha ao obter ou comparar o PID fecha a operação.

## Envelope de aplicação v2

Todas as cinco operações MAC-003 — abrir/fechar sessão, criar/revogar grant e listar missão — são enviadas por `POST /v2/secure`. Rotas `/v1/app/*` em texto claro não pertencem à allowlist externa e são recusadas. Não há fallback de versão: o cliente valida a versão/build do runtime, e qualquer lado que não suporte a rota ou envelope v2 falha fechado.

O envelope binário externo é:

```text
nonce[16] || ciphertext[n] || tag_hmac_sha256[32]
```

O nonce é `prefixo aleatório da geração[8] || sequência big-endian[8]`, com sequência iniciando em 1 e avançando por operação. A solicitação decifrada tem o framing:

```text
versão:u8 (=2) || método:u8 (=1, POST) || tamanho_path:u16_be || tamanho_corpo:u32_be || path_ascii || corpo_utf8
```

A resposta decifrada contém `versão:u8 (=2) || status:u16_be || tamanho_corpo:u32_be || corpo`. Cliente e servidor mantêm os limites MAC-003 existentes. O nonce da resposta deve ser idêntico ao nonce da solicitação.

Para cada propósito (`encryption`, `authentication`) e direção (`request`, `response`), a chave é derivada como HMAC-SHA-256 com a capability da geração e contexto `jarvis-local-envelope-v2\0 || propósito || 0 || direção || 0 || instance_id_ascii`. A cifra é AES-256-CTR. O tag HMAC-SHA-256 cobre domínio, instance ID, direção, rota externa `/v2/secure`, nonce e ciphertext. As chaves de cifra/autenticação e as direções são distintas. A verificação do tag ocorre antes da decifragem e comparação é em tempo constante. Rust usa CommonCrypto do macOS; FastAPI usa a dependência `cryptography` já fixada no ambiente do projeto. Nenhuma dependência ou lockfile foi alterado.

O servidor fixa o primeiro prefixo válido da geração e aceita apenas sequências estritamente crescentes; prefixo diferente, sequência zero ou repetida/antiga é recusada antes do dispatch. O cliente serializa chamadas em uma sessão, gera o nonce por geração e rejeita tag incorreto, geração distinta ou resposta associada a outro nonce. O servidor autentica cada solicitação antes de abrir path/corpo; o cliente autentica cada resposta antes de expor qualquer resultado ao Runtime Manager.

## Troca de socket e limite de confiança

O probe adversarial reproduz a ordem da falha: o FastAPI real responde a prova HMAC, seu socket é renomeado e outro processo do mesmo UID liga um listener falso ao pathname original antes da operação. O cliente conecta, consulta o PID do peer e rejeita a conexão antes do primeiro byte HTTP; o listener registra zero bytes, e uma resposta HTTP forjada que oferece não pode ser aceita pelo cliente. O teste executa essa troca antes de abrir sessão, criar grant, revogar grant e listar missão. Em seguida, a jornada legítima continua pelo FastAPI real.

Um processo sem a capability não consegue criar envelope aceito; envelope forjado ou de outra geração recebe rejeição, texto claro em rotas de aplicação não é encaminhado, e replay de envelope autenticado é recusado. Um relay que não substitua o peer PID pode causar indisponibilidade, mas cifragem e tags impedem que leia ou modifique o conteúdo. A garantia não cobre inspeção privilegiada da memória, comprometimento de um dos processos, root/admin ou defeito do kernel/criptografia. Um processo local ainda pode causar DoS e disputar o pathname; a detecção deve falhar fechado.

## Evidência nesta branch

Os testes de regressão são `test_native_protocol_requires_encrypted_authenticated_v2_and_replay_rejection`, os fluxos de processo FastAPI supervisionado e STOP/EOF/crash/restart, testes Rust de cifra, confidencialidade, tamper, resposta e geração, e `mac003_production_supervisor`. O último compila a biblioteca como dependência sem `cfg(test)`, usa o RuntimeManager de produção para iniciar FastAPI, aguarda READY autenticado e exercita a substituição de socket, as operações G5 legítimas e STOP/EOF/crash/reap. Resultados efetivamente executados e falhas intermediárias ficam registrados no relatório `MAC_002_2_REPORT.md`.
