# MAC-002.2 — Canal UDS autenticado e cifrado, protocolo v3

## Estado e escopo

Candidata em `feat/jarvis-g6-mac-002-2-ctr-fix`, derivada de `d898ea287338613ec4adb546dcd9952e400964a5` (base anterior `5dd976e94acff09316381e455d4bd5ac1543ce38`). Corrige exclusivamente o P1 de reutilização de keystream CTR. Não declara aceite de MAC-002.2/MAC-003 nem fecha o smoke Tauri/WebView.

A reauditoria demonstrou reutilização de blocos de contador entre mensagens multibloco consecutivas e recuperação de plaintext com outro plaintext conhecido. Não demonstrou captura dos ciphertexts por atacante same-UID após a proteção por PID, nem falsificação de HMAC. A construção v2 não deve ser reutilizada.

Não existe adapter AEAD interoperável já implementado nos dois lados do projeto. Python dispõe de `cryptography`, mas Rust utiliza somente CommonCrypto por FFI para CTR/HMAC. Mantém-se Encrypt-then-MAC, com partição determinística de contador, sem nova dependência nem mudança de lockfiles.

## Fronteiras preservadas e versões

UDS-only por geração; sem TCP. WebView chama comandos Tauri tipados. Capability, endpoint e material sensível permanecem no processo Rust e no FastAPI supervisionado. Spawn, stdin/EOF, STOP, crash, reap e cleanup continuam pertencendo ao supervisor. Nenhuma mudança em G5, DTOs internos, migrations ou SQLite.

O cliente consulta `LOCAL_PEERPID` de cada conexão e exige o PID do child supervisionado antes de escrever qualquer byte HTTP. O servidor não autentica o PID do cliente: autentica a capability do envelope antes de descriptografar e fazer dispatch.

Health e version precedem a prova com nonce CSPRNG novo e HMAC no domínio `jarvis-local-transport-proof-v3`. A versão é `3` e o build é `g6-mac-002-2-encrypted-uds-v3`. A prova continua autenticando o runtime para o cliente. Versão, build, domínio, byte de framing e rota são explícitos; nenhum fallback v2. `/v2/secure` e rotas G5 em texto claro não pertencem à allowlist externa.

## Framing e autenticação

Todas as cinco operações usam `POST /v3/secure`, HTTP/1.1, `Host: jarvis.local`, `Connection: close`, comprimento explícito e `Content-Type: application/octet-stream`.

```text
nonce[16] || ciphertext[n] || tag_hmac_sha256[32]
nonce = sequence:u64_be || zero:u64_be
pedido = versão:u8(3) || método:u8(1=POST) || path_len:u16_be || body_len:u32_be || path_ascii || body_utf8
resposta = versão:u8(3) || status:u16_be || body_len:u32_be || body
```

A resposta repete o nonce do pedido. Rust rejeita nonce inesperado antes de expor qualquer resultado. O HMAC cobre `jarvis-local-envelope-v3\0 || instance_id || 0 || direção || 0 || /v3/secure || 0 || nonce || ciphertext`. Método/operação/path/corpo e status/corpo são vinculados pelo ciphertext autenticado; comprimentos e versão também. Headers de transporte não carregam decisões G5.

Para propósito (`encryption`, `authentication`) e direção (`request`, `response`), a chave é HMAC-SHA-256 da capability com `jarvis-local-envelope-v3\0 || propósito || 0 || direção || 0 || instance_id_ascii`. Chaves de cifra/MAC e request/response são separadas; cada nova geração cria nova capability CSPRNG e novo contexto. Não restaurar/reutilizar capability e estado de sequência de uma geração encerrada.

HMAC de 32 bytes é validado antes de qualquer descriptografia. Python usa `hmac.compare_digest`; Rust compara comprimento fixo acumulando XOR. Após autenticar, ambos validam tamanho e nonce canônico antes de qualquer outra operação criptográfica. No pedido, o servidor então reserva a sequência sob o lock e só depois invoca CTR. Uma falha de HMAC, um nonce não canônico ou um ciphertext acima do limite não consome sequência. Uma mensagem autenticada e canônica consome a sequência mesmo se o frame ou o dispatch falharem depois; o replay dessa sequência não volta a descriptografar nem a despachar. Falhas devolvem somente categorias genéricas, sem plaintext ou segredos.

## Partição formal do contador

O nonce externo também é o contador inicial AES-CTR: `s_be64 || 0_be64`. `s` começa em 1, cresce estritamente e nunca volta a zero. Rust serializa a alocação e o seal sob o mesmo mutex da capability. O incremento é checked; depois de `2^64-1`, recusa novas mensagens antes da cifra. Uma tentativa que falha consome sua sequência, sem retry com o mesmo nonce. A desativação, ainda sob esse mutex, marca a sessão inativa, apaga o segredo e estaciona a sequência em `2^64-1`. Ela não volta a zero e não permite selar ou enviar com a capability retirada. O envio também recusa sessão inativa imediatamente antes de escrever no socket.

O servidor aceita apenas nonce com `s != 0` e metade baixa zero. Sob lock, reserva `s` maior que `last_sequence` antes do AES-CTR e do dispatch. Cada pedido reservado produz no máximo um envelope de resposta, mesmo para falha G5. Uma resposta reutiliza `s` somente sob a chave distinta de response.

Para mensagem com `L` bytes, `B = ceil(L/16)`. Os blocos AES de `s` são:

```text
[s * 2^64, s * 2^64 + B - 1]
```

| Direção | Limite de ciphertext/plaintext | Máximo de blocos |
|---|---:|---:|
| request | 1232 bytes (envelope externo 1280 menos 48) | 77 |
| response | 2055 bytes (corpo 2048 mais framing 7) | 129 |

Os corpos G5 continuam limitados a 1024 bytes no pedido e 2048 na resposta; os limites da tabela são limites criptográficos adicionais. Ambos os seal/open de produção impõem os limites. `B <= 129 < 2^64`, portanto o contador de bloco nunca invade a sequência. Para `s < t`, o último contador de `s` é menor que `t * 2^64`. Mesmo para `s = 2^64-1`, o contador final é menor que `2^128`; não há wrap. A garantia depende do estado monotônico único da geração e da separação de chaves, não de nonces aleatórios.

CommonCrypto usa explicitamente `kCCModeOptionCTR_BE=2`. Python usa `cryptography.modes.CTR`. Testes reais comparam blocos 0, 1, 77 e 128 com cifras independentes iniciadas em `s_be64 || block_be64`, incluindo sequências próximas do máximo. Isso verifica a progressão efetiva, além do cálculo formal. Ver [NIST SP 800-38A, seção 6.5 e apêndice B](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38a.pdf).

## Evidência e limites

Regressões usam funções de produção: interseção de blocos em toda a mensagem multibloco consecutiva, nas duas direções, com a construção antiga detectada e o v3 sem blocos em comum; limites, sequência máxima/wrap, nonce inválido, tag/ciphertext alterados, replay sem nova cifra, HMAC inválido sem consumo de sequência, 32 pedidos concorrentes do mesmo nonce, desativação concorrente, geração e versão antiga. A interoperabilidade compara ciphertext/tag byte a byte de CommonCrypto e Python e abre em ambos os lados, por pipes privados em memória; nada sensível é registrado. A integração do supervisor usa FastAPI real, prova, operações G5, substituição same-UID pós-prova, STOP/EOF/crash/restart/reap/cleanup.

O listener falso continua sendo recusado antes de receber bytes. Um processo local pode causar DoS ou disputar pathname. Não há proteção contra comprometimento de processo, inspeção privilegiada de memória, root/admin ou falha do kernel. Não se promete invulnerabilidade criptográfica absoluta nem proteção contra análise de comprimento/tráfego. Resultados e falhas intermediárias estão em [MAC_002_2_REPORT.md](MAC_002_2_REPORT.md).
