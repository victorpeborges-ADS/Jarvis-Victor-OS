# Leitura lexical e protocolo para um provider real — 17/10/2026

A leitura usa capturas do banco local aberto e documentos sintéticos autorizados em `dom_synthetic_a`. O caminho do app agora é `createG5Ipc().groundedRead` → Tauri `g5_conversation_ask` → rota fechada `POST /v1/app/conversation/ask` → `GroundedRead` → `ConversationGateway` com `FakeProvider`. A rota recebe, nessa ordem, `session_token`, `conversation_id`, `question`, `domain_id`; a API valida sessão e domínio antes de ler. Rust e Python mantêm allowlists exatas, e o parser TypeScript rejeita chaves/códigos desconhecidos. Resposta limita o corpo codificado a 2048 bytes; o transporte local autenticado aplica também seu próprio teto ao envelope. A UI descarta resposta de geração/conversa anterior. Não há migration `0021`, FTS nem busca vetorial. O estado de DEC-14 nesta data foi superado em 23/10/2026: o identificador opaco já persiste só os metadados mínimos; ver a seção final.

O teto de 2048 bytes aplica-se ao corpo de resposta da aplicação. O envelope cifrado acrescenta 16 bytes de nonce, 32 de tag e 7 de framing, portanto o teto de transporte é 2103 bytes; Python e Rust declaram o mesmo valor. Testes da camada Python abrem o envelope e confirmam corpo e envelope nos dois limites, e recusam corpo acima de 2048. O teste da conversa também excede o teto do corpo e confirma recusa sem evidência publicada.

O fluxo foi exercitado pela rota autenticada no processo supervisionado da API, com banco e captura temporários, além dos testes de contrato Python, Rust e TypeScript. Isso verifica o caminho de protocolo sem abrir a janela. Integração visual: NOT TESTED.

## Regra lexical

O texto da pergunta e o da fonte são partidos em tokens de letras e números. A comparação usa a mesma dobra da captura: NFD, sem marca combinante, casefold. Entra token com pelo menos quatro caracteres depois da dobra. A fonte sustenta a pergunta quando um token dela é igual a um token da fonte. O recorte citado é o trecho original desse token, não uma paráfrase. Sem recorte, o estado é `insufficient_basis` e o texto visível fica vazio. O provider falso não é chamado nesse caso.

Essa regra não foi ajustada com o conjunto medido. Os casos de regressão (sessão fechada, outro domínio, campo extra, injeção, teto de 2048 bytes, token que é só prefixo de outra palavra) não entram no ajuste.

## Decisão: lexical, não vetorial

Não há benchmark sintético que mostre ganho de busca vetorial ou híbrida sem custo de privacidade ou de orçamento. A decisão deste passo é permanecer na comparação de tokens. FTS só seria uma tabela nova; o conjunto sintético cabe na leitura em memória. A migration `0021` não foi criada.

## Medição deste passo

Uma execução local do conjunto separado, em 17/10/2026, no `pytest` de `test_grounded_read.py`:

| Medida | Valor |
|---|---|
| Denominador | 8 |
| Acertos | 8 |
| Falhas | 0 |
| Latência p50 | 4,424 ms |
| Latência máxima | 7,793 ms |

Qualidade, aqui, é citação do recorte certo, recusa quando falta base e ausência de efeito de ferramenta. Não é nota de inteligência. A latência é a de `ask` nessa máquina, com banco temporário, não um limite de serviço.

## Protocolo para comparar um provider real com o falso

Estado: BLOCKED. Não executar até autorização específica de provider, modelo, dados permitidos e custo. Este documento não faz a chamada e não lê segredo.

### Tarefas

Repetir o mesmo conjunto de oito perguntas sintéticas e, em separado, os casos de regressão. O provider real recebe a pergunta e os recortes já autorizados como dados. Não recebe token de sessão, não recebe o texto como instrução de sistema e não recebe pasta real.

### Critérios de qualidade

- Todo trecho marcado como evidência é substring da fonte autorizada no domínio `dom_synthetic_a`.
- Sem substring que sustente a pergunta, o estado é base insuficiente e o texto visível fica vazio.
- Nenhuma chamada de ferramenta, nenhuma mudança de allowlist e nenhuma mudança de orçamento.
- Inferência, se um dia existir, não pode ser rotulada como evidência.

### Privacidade

Somente dados sintéticos até outra autorização. Fora do domínio e sem sessão válida, não há leitura. O banco diário, `.env` e pastas reais ficam de fora. O id de conversa não vira registro durável.

### Latência

Medir o mesmo intervalo, em volta da chamada, no mesmo denominador. Publicar p50 e máximo ao lado do baseline falso desta página. Não tratar o tempo do falso como tempo de rede.

### Custo estimado

O falso permanece `unmeasured`, não zero. O real só roda depois de um teto de gasto aceito. Se o preço ou os tokens não forem medidos, o relatório diz `unmeasured`. Não converter custo desconhecido em zero.

### Tratamento de dados

Perguntas, capturas e documentos do ensaio são sintéticos e morrem com o processo de teste. Não há retenção, não há log do recorte e não há envio fora da máquina neste passo. Um provider real exigiria declarar o que sai da máquina, por quanto tempo e com qual direito de apagar.

## Caminho da interface confirmado — 23/10/2026

A pergunta já entra por `App.tsx` → `createG5Ipc().groundedRead` → `g5_conversation_ask` → `POST /v1/app/conversation/ask`. O servidor revalida sessão e domínio e escolhe somente `read_capture`, `read_confirmed_fact` e `read_authorized_document`. Campo extra, inclusive um nome de ferramenta, é recusado antes da leitura. Nesta rodada, a rota autenticada citou um fato confirmado sintético: texto `estoque`, fonte `confirmed_fact` no domínio `dom_synthetic_a`, e as palavras de instrução do mesmo registro não entraram na resposta. Captura, documento autorizado, base insuficiente, sessão encerrada, domínio inválido, cancelamento, corpo acima de 2.048 bytes e artefato com origem/versão/hash já estavam cobertos; o fragmento maior continua em `read_fragment`, sem rota nova e sem elevar o teto. Smoke visual NOT TESTED. Provider real continua BLOCKED.
