# MAC-003 — Protocolo de aplicação G5 sobre UDS

## Estado e escopo

Protocolo de aplicação aprovado para o primeiro marco MAC-003. Este documento precede a implementação e fixa a allowlist, o framing, os limites e o fluxo de autorização. O escopo é local e sintético; não habilita fontes externas, dados pessoais, workers adicionais ou distribuição do runtime.

O protocolo MAC-002 continua responsável pelo ownership e lifecycle do processo, pelo socket UDS da geração e pela prova HMAC que autentica o runtime para o cliente. A emenda MAC-002.2 autentica também cada operação G5 e cifra pedidos/respostas no envelope externo v3. MAC-003 define operações de aplicação com caminhos e DTOs fixos; o framing de campos descrito abaixo permanece dentro do ciphertext. A capability MAC-002 não é sessão, grant nem credencial G5.

## Contrato de transporte preservado

O UDS usa HTTP/1.1, `Host: jarvis.local`, uma requisição por conexão, `Connection: close`, `Content-Length` explícito e `Content-Type: text/plain` para controle. As operações de aplicação usam somente `POST /v3/secure`, com `Content-Type: application/octet-stream`; path e corpo MAC-003 ficam dentro do envelope AES-256-CTR + HMAC-SHA-256. O cliente mantém timeout, limites, validação de framing, validação do host, verificação do PID do peer antes de escrever e rejeição de `Origin` e headers desconhecidos. Não há TCP, URL de rede, CORS ou transporte direto pela WebView. A especificação do envelope está em [MAC-002.2](../g6-2/MAC_002_2_ENCRYPTED_UDS.md).

As operações de controle permanecem:

| Método | Caminho | Corpo | Resultado |
|---|---|---:|---|
| `GET` | `/v1/health` | vazio | `ok\n` |
| `GET` | `/v1/version` | vazio | `protocol_version`, `runtime_kind`, `instance_id`, `build` |
| `POST` | `/v1/instance-proof` | nonce hexadecimal de 32 bytes | campos atuais de identidade, `pong:<instance_id>` e HMAC-SHA-256 |

O transporte candidato MAC-002.2 usa versão `3` e domínio de prova `jarvis-local-transport-proof-v3`; cliente e servidor falham fechados em versões/builds/rotas desconhecidos. A allowlist externa remove os caminhos G5 em texto claro. O envelope v3 cifra e autentica cada operação; o servidor também rejeita replay de sequência dentro da geração. A capability continua entrando pelo registro privado de stdin e não aparece em argv, environment, URL, frontend, logs ou erros. EOF e STOP continuam controlados pelo supervisor, sem subprocesso descendente.

## Framing do protocolo de aplicação v1

O protocolo de aplicação usa somente `POST` em caminhos abaixo de `/v1/app/`. Cada corpo é UTF-8 representado como linhas `chave=valor\n`; nomes de campo são ASCII fixos e valores usam percent-encoding RFC 3986 (`%HH`) de seus bytes UTF-8. Espaço é `%20`, nunca `+`. Não são aceitos nomes duplicados, desconhecidos, ausentes, linhas extras, sequências `%` inválidas ou conteúdo após a última quebra de linha. A versão é o segmento `/v1/app/` do caminho.

Limites independentes do handshake:

| Elemento | Limite |
|---|---:|
| Headers HTTP | 1.024 bytes |
| Corpo de pedido de aplicação | 1.024 bytes |
| Corpo de resposta de aplicação | 2.048 bytes |
| Timeout do cliente por pedido; leitura do corpo no servidor | 900 ms |
| Resultado de listagem | no máximo 1 missão |
| Passphrase nativa | 12–128 bytes UTF-8 |
| Título na resposta | no máximo 80 caracteres Unicode |

O pedido Rust rejeita corpos maiores antes de conectar. O FastAPI rejeita tamanho, framing ou campos inválidos sem ecoar conteúdo. Respostas de aplicação válidas têm status interno `200` e envelope textual MAC-003, protegido pelo envelope criptográfico externo; erros de autorização são códigos fechados no envelope, sem detalhe, passphrase ou token. Falhas de protocolo continuam sendo erro de transporte.

## Allowlist de aplicação v1

| Método e caminho | Campos exatos do pedido | Resposta de sucesso |
|---|---|---|
| `POST /v1/app/session/open` | `passphrase` | `ok=true`, `principal=owner`, `session_token`, `csrf_token`, `expires_at_epoch_us`, `expires_at` |
| `POST /v1/app/grants/mission-read` | `session_token`, `csrf_token`, `domain_id` | `ok=true`, `grant_id`, `domain_id`, `expires_at_epoch_us`, `expires_at` |
| `POST /v1/app/grants/mission-read/revoke` | `session_token`, `csrf_token`, `grant_id` | `ok=true`, `revoked=true` |
| `POST /v1/app/session/close` | `session_token`, `csrf_token` | `ok=true`, `closed=true` |
| `POST /v1/app/missions/list` | `session_token`, `domain_id` | `ok=true`, `dataset`, `count` e campos da única missão, se houver |

Cada resposta contém apenas campos definidos para a operação. Para listagem, o DTO é `{dataset, count, mission_id?, title?, domain_id?, status?, revision?}`. `dataset` deve ser `api_synthetic`; o DTO não inclui tarefas, artefatos, proveniência, tokens, grants ou JSON interno da missão. `count` é `0` ou `1`. A consulta reutiliza `MissionRepository.list_page` com limite fixo `1`, sem cursor controlável pelo cliente.

Os códigos de erro permitidos são `credential_rejected`, `session_required`, `grant_required`, `grant_active`, `scope_invalid`, `grant_conflict`, `grant_expired` e `operation_failed`. Nenhuma resposta retorna entrada original, passphrase, token, stack trace ou mensagem interna.

### Limites G5 fixos do primeiro marco

- A concessão nativa permite exclusivamente `connector=mission_sim`, `permission=read`, `resource_ids=[mission:read]`, um único domínio canônico e validade de até 60 minutos.
- A sessão mantém o TTL existente do G5 (12 horas), sem persistir a credencial, o token ou o CSRF.
- O primeiro UI seleciona explicitamente `dom_synthetic_a`; não aceita domínio ou validade arbitrários vindos do WebView.
- `mission:list` exige sessão ativa e concessão ativa para `dom_synthetic_a`. A checagem usa `mission_read_scope_confirmed`, mantendo a ordem existente de lock de autorização antes da leitura SQLite. Títulos acima de 80 caracteres não entram no DTO do primeiro marco; o contrato público G5 continua aceitando até 240.
- Não existem operações de escrita, execução, transição, review, importação ou leitura genérica neste protocolo.

## IPC tipado e segredos

Comandos Tauri MAC-003 sem rota, método, path, ID de instância ou escopo controlável pelo WebView:

- `g5_session_status()` — retorna estado e expiração, nunca token.
- `g5_session_open(passphrase)` — recebe a credencial digitada; o WebView limpa o campo depois da resposta. Rust encaminha a credencial apenas no corpo da operação `session/open` e zera os buffers temporários.
- `g5_mission_read_grant_create()` — só é chamado pelo botão após consentimento visível para o domínio e validade fixos.
- `g5_mission_read_grant_revoke()` — revoga a concessão nativa ativa.
- `g5_session_close()` — encerra a sessão explicitamente; invalida atomicamente todos os grants daquela sessão no servidor e limpa o cache Rust.
- `g5_missions_list()` — retorna somente o DTO de missão limitado acima.

No cliente, o token de sessão, CSRF e ID do grant ficam somente em memória no `RuntimeManager`, vinculados ao `runtime_instance_id`; só Rust os envia ao backend dentro do corpo cifrado/autenticado no UDS. A WebView recebe estado e DTOs limitados, nunca esses tokens. Expirações Unix fornecidas pela API são inteiros exatos em microssegundos (`expires_at_epoch_us`), calculados sem ponto flutuante a partir do datetime autoritativo. Rust compara em microssegundos, sem tolerância ou arredondamento de validade; o servidor revalida cada leitura. Esses instantes permitem limpar tokens locais vencidos; também são apagados no stop, EOF, crash, restart e falha de geração. No servidor, cada grant pertence ao token da sessão que o criou (apenas em memória; nunca no DTO), e sessões e grants continuam voláteis conforme G5 para que as checagens existentes possam validá-los. A passphrase digitada não é persistida nem registrada. O valor de comparação continua sendo a configuração local existente `JARVIS_LOCAL_PASSPHRASE`; o desktop não a inventa, não a muda e não a grava.

O cliente filho usa o interpretador Python 3.12 diretamente, sem shell ou launcher intermediário; stdin/stdout pertencem ao supervisor. O registro de capability continua privado em stdin. Somente a configuração local estritamente necessária para o runner pode ser encaminhada ao processo; capability nunca é environment. O runner desktop serve apenas o app FastAPI nativo em UDS, sem montar as rotas web, Swagger/OpenAPI ou endpoints DEMO no socket nativo. O runner oficial web continua loopback e suas validações de Origin/CSRF/host permanecem inalteradas.

## Sessão, concessão e reinício

1. A pessoa informa explicitamente a passphrase local existente. O backend valida a passphrase e o rate limit G5 e cria sessão volátil; não cria grant.
2. A UI apresenta o domínio `dom_synthetic_a`, o recurso `mission:read` e a validade de 60 minutos. A pessoa confirma; só então Rust solicita a criação do grant.
3. O servidor define a expiração de 60 minutos na confirmação do grant. Cada leitura envia o token e o domínio pelo canal privado Rust→UDS. G5 revalida a sessão e o grant no servidor antes da consulta.
4. Revogação exige ação explícita. Logout invalida os grants vinculados à sessão sob o mesmo lock de autorização.
5. Logout permanece disponível com grant ativo. Fechamento ou expiração invalida os grants da sessão que os criou; uma sessão nova nunca herda autorização ou conflito da anterior. A expiração é observada na validação ou varredura de grants, sem scheduler. STOP/EOF/crash/restart encerram o processo FastAPI e descartam seus estados voláteis. Tokens locais são limpos; a nova geração não herda sessão ou grant e exige novo login e nova confirmação.

## Arquivos e plano de implementação

Alterar somente nesta branch/worktree:

- `docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md`: este contrato, escrito antes da implementação.
- `apps/api/serve.py`, `main.py` e novos módulos nativos: execução FastAPI direta em UDS, handshake MAC-002 e allowlist nativa isolada; rotas web mantêm comportamento atual.
- `apps/api/local_security.py` e novo adapter: reutilizar validação de passphrase/rate limit, estado volátil, sessão, CSRF, criação/revogação de grants e guarda de leitura G5; nenhum schema SQLite ou migration.
- `apps/desktop/src-tauri/src/transport.rs`, `runtime_manager.rs` e `lib.rs`: chamadas de rotas fechadas, parsing estrito, armazenamento de sessão/grant por geração e comandos tipados. O supervisor continua dono do único processo filho.
- `apps/desktop/src/runtimeCommand.ts`, `App.tsx` e `App.css`: interface PT-BR de sessão, consentimento, revogação e leitura sintética; nenhum segredo persistido.
- testes API/desktop focados e matriz de gates do MAC-002/MAC-001; banco temporário, passphrase/identidade sintéticas e fixture de missão somente em testes.

## Aceite do primeiro marco

READY só é publicado depois que o runner conclui o startup FastAPI e o Rust valida health, versão e proof HMAC daquela geração. O supervisor mantém a capacidade de processar STOP enquanto a prova roda; prova inválida mata e recolhe o mesmo `Child`. O fluxo aprovado retorna no WebView a missão sintética pela operação fixa, depois de sessão aberta e grant confirmado.

O aceite inclui regressões MAC-002 de runtime falso, HMAC, nonce/replay, geração velha e isolamento entre managers; STOP, EOF, crash/restart/reap sem órfãos; sessão/grant ausentes, inválidos, expirados e revogados; isolamento por geração; ausência de capability/token nos canais proibidos; ausência de listeners TCP; rotas web inalteradas; nenhum dado real, migration, contrato SQLite, dependência ou lockfile alterado.


## Emenda aditiva: histórico paginado de workflows — 2026-10-14

O conteúdo anterior registra o primeiro marco; os fluxos atuais de credencial nativa e workflows são descritos em [WORKFLOW_EXECUTOR.md](../WORKFLOW_EXECUTOR.md). Esta emenda adiciona somente uma operação fechada, preservando as operações anteriores e o envelope v3:

| Operação | Campos exatos e ordenados | Sucesso |
|---|---|---|
| `POST /v1/app/workflows/page` | `session_token`, `cursor` | `ok=true`, `tasks_json`, `next_cursor` |

IPC `g5_workflow_page(cursor)` não aceita método/URL/token/limite. Resposta com campos novos pertence somente a esta operação; `/workflows/list` permanece intacta. Cursores inválidos e campos extras recebem o código já existente do executor `schema_rejected`; item que não cabe recebe `limit_exceeded`. Códigos desconhecidos permanecem recusados. Não exige nova versão porque nenhum DTO ou semântica de operação existente foi modificado. Clientes antigos não recebem respostas desta rota; runtimes antigos a recusam fechada. O cliente novo não faz fallback silencioso.

Keyset por `(created_at,id)` imutáveis, limite de quatro itens reduzido pelo tamanho serializado, cursor canônico de até 80 bytes e fim com cursor vazio. Corpo percent-encoded da página até 1.792 bytes, incluindo cursor; frame e envelope criptográfico total abaixo de 2.048 bytes, sem ampliar limites globais. Contrato completo de remoção/inserções/item grande e evidências no documento do executor. Nenhuma mudança em autorização, capability, HMAC, partições CTR, replay, PID do peer ou listener. Allowlist contém somente essa nova rota exata, testada no backend e no Rust.
