# MAC-002.2 — Relatório da correção do transporte UDS

## Estado e base

- Branch: `feat/jarvis-g6-mac-002-2-aead-uds-remediation`.
- Base exata: `5dd976e94acff09316381e455d4bd5ac1543ce38`.
- A candidata permanece em revisão independente; este relatório não declara aceite, integração à `main` nem fechamento do smoke Tauri/WebView.
- A especificação normativa desta implementação está em [MAC_002_2_ENCRYPTED_UDS.md](MAC_002_2_ENCRYPTED_UDS.md).

## Achado e correção

O probe anterior mostrou que a prova HMAC autenticava o servidor apenas naquela conexão; reconectar pelo pathname deixava uma janela para um listener do mesmo UID receber dados G5 e falsificar a resposta. MAC-002.2 fecha a janela em duas camadas: Rust consulta `LOCAL_PEERPID` de cada conexão e exige o PID exato do child supervisionado antes de escrever cabeçalhos ou corpo; cada operação G5 também usa envelope externo v2 com confidencialidade AES-256-CTR e autenticação HMAC-SHA-256. O servidor autentica cada envelope antes do dispatch, e Rust verifica nonce, geração e tag antes de expor uma resposta.

Após uma prova genuína do FastAPI, o teste de integração renomeia o socket real e liga um listener falso do mesmo UID ao pathname original. O listener falso envia uma resposta HTTP forjada, aceita a conexão e recebe `payload=0`; Rust retorna `peer_rejected` antes de enviar o pedido. O teste repete a substituição antes de abrir sessão, criar grant, revogar grant e listar missão. A chamada seguinte ocorre contra o FastAPI real e confirma que operação legítima segue funcionando.

Um processo same-UID sem capability não acessa operações por rotas G5 em texto claro: a prova direta executada no UDS obteve 404 para abrir/fechar sessão, criar/revogar grant e listar missão. Testes de envelope recusam tag inválido (401), geração antiga e replay (409). A prova de handshake continua autenticando o runtime para o cliente; não é chamada de autenticação mútua sozinha.

## Evidência executada

| Comando | Resultado |
|---|---|
| `uv run --locked --python 3.12 pytest -q test_native_app_api.py test_native_runtime_process.py` em `apps/api` | PASS — 16 aprovados; um aviso de depreciação do `starlette.testclient`/`httpx`. |
| `rtk proxy cargo test --locked --features mac003-production-supervisor-test transport::tests -- --test-threads=1` em `apps/desktop/src-tauri` | PASS — 21 aprovados, 0 falhos, 3 ignorados (entrypoint subordinado e stresses explicitamente marcados), 62 filtrados. Inclui vetor AES-CTR, ocultação dos campos sensíveis, alteração de resposta e geração distinta. |
| `rtk proxy cargo test --locked --features mac003-production-supervisor-test separate_managers_and_stale_generations_cannot_cross_authenticate -- --test-threads=1` | PASS — uma regressão de geração obsoleta/manager distinto aprovada; peer de outro PID é recusado antes do HMAC. |
| `rtk proxy cargo test --locked --features mac003-production-supervisor-test --test mac003_production_supervisor -- --nocapture` | PASS — compila a biblioteca como dependência, sem `cfg(test)`, e percorre o launcher real do RuntimeManager. Prova v2/READY, quatro trocas pós-prova com listener falso e zero bytes recebidos, G5 legítimo, bloqueio de operações same-UID sem envelope, STOP/reap/UDS cleanup, EOF/reap, crash/reap e restart/READY/STOP. |
| `rtk proxy cargo fmt --all -- --check` | PASS. |
| `rtk proxy cargo build --locked` | PASS — build nativo debug. |
| `rtk proxy git diff --check` | PASS. |

Os testes de API incluem envelope inválido, sequência replay e chave de geração antiga. O fluxo de processo usa um codec de referência independente para abrir a resposta cifrada do FastAPI e percorre sessão, consentimento, leitura, revogação, negativa e STOP/EOF/crash/restart.

Após a integração, as asserções do RuntimeManager confirmaram reap e remoção dos UDS por geração; `pgrep` não encontrou `serve.py --desktop-runtime`, e as buscas de UDS e diretórios temporários `mac003-production-supervisor-*` não encontraram resíduos.

## Falhas intermediárias preservadas

- Uma tentativa inicial de pytest sem selecionar o Python fixado usou Python 3.14 e falhou na coleta por incompatibilidade de validação de status 204 do FastAPI. O teste foi então executado com `--locked --python 3.12`.
- A primeira rodada com Python 3.12 teve 15 aprovados e uma asserção antiga esperando 400; a nova allowlist externa corretamente devolvia 404 para G5 em texto claro. A expectativa foi atualizada e a repetição passou com 16.
- Uma execução Rust inicial sem a feature `mac003-production-supervisor-test` não compilou o entrypoint de integração protegido pela feature. Os testes focados foram executados com a feature habilitada.
- Uma compilação intermediária de Rust encontrou um erro de borrow-checker (`E0502`) no código novo; foi corrigido antes dos testes focados. A primeira rodada unitária também teve duas falhas em respostas fake de controle sem `Content-Type`; o parser agora mantém esse header opcional apenas para controle e exige tipo exato no envelope seguro.
- A primeira execução do supervisor real falhou no READY porque o parser Rust não aceitava o `text/plain; charset=utf-8` emitido pelo FastAPI. O parser passou a aceitar esse único parâmetro em respostas de controle; o envelope seguro continua exigindo `application/octet-stream` exato.
- A primeira versão do probe movia o socket antes de iniciar a operação e, por isso, não reproduzia a troca depois da prova. A falha revelou que o caminho de teste ainda precisava ser corrigido; a renomeação foi movida para o callback pós-prova e sincronizada depois do `listen` do fake.
- Uma versão intermediária do probe same-UID falhou em parsing auxiliar do corpo. Como os códigos HTTP bastam para a negativa de rotas em texto claro, o probe foi simplificado para registrar somente os status. A execução final completa passou.
- O teste de manager/geração obsoleta inicialmente esperava `proof_rejected`; depois da proteção por PID, a tentativa entre managers é recusada antes do handshake como `peer_rejected`. A expectativa foi atualizada e o teste isolado passou.
- Ao alinhar o sufixo do `BUILD_ID` de v1 para v2 em ambos os lados, um teste de processo ainda tinha a string v1 literal e falhou (15 aprovados, 1 falho). A fixture independente foi alinhada e a suíte final passou com 16.
- A primeira verificação de formato Rust apontou uma quebra de linha no probe de teste; `cargo fmt --all` aplicou o formato e a checagem final passou.

## Escopo preservado e limites

Não foram alterados G5, rotas/DTOs internos, migrations, contratos SQLite, lockfiles ou dependências. UDS, stdin/EOF, STOP, supervisor, reap e isolamento por geração permanecem. Não há listener TCP. A solução não cobre processo comprometido, inspeção privilegiada de memória, root/admin ou falha do kernel; outro processo local ainda pode provocar DoS. O smoke da janela Tauri/WebView segue gate separado e aberto até existir evidência real dessa jornada.

## Decisão pendente

Reauditoria independente do código, framing binário, primitive crypto/CommonCrypto, autenticação por PID e testes adversariais. Não há autorização para merge, push, tag, deploy ou integração à `main`.
