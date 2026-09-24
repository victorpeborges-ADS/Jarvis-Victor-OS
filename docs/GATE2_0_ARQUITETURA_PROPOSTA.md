# Gate 2.0 — Proposta de arquitetura

**Estado:** referência arquitetural aprovada. A fundação B e o C.1 foram tecnicamente aceitos; C.2 foi autorizado em branch dedicada apenas para backup cifrado e recuperação com dados sintéticos.
**Base original da proposta:** `main` @ `ef5d3cd`, tag `gate1-accepted-v0.1`. A aprovação e consolidação B estão registradas em `docs/GATE2_0B_2_HARDENING.md`.
**Data:** 23/09/2026.  
**Restrição:** qualquer implementação depende de aceite explícito e delimitado. C.1 está aceito; o aceite separado do C.2 cobre apenas backup cifrado e restauração isolada com bancos sintéticos, não dados reais, OAuth ou conectores.

> C.1 autorizou a memória local vazia e testes sintéticos. A autorização atual do C.2 é limitada a backup/restauração sintéticos em diretório isolado; retenção automática, persistência de chaves, substituição de base ativa, dados pessoais, OAuth ou conectores continuam pendentes de decisões e aceites próprios.

O Blueprint descreve o Gate 2 como Calendar e Gmail somente leitura. Esta proposta estreita a primeira conexão real para **uma conta pessoal do Google Calendar, somente leitura**. Gmail, Drive e conversa com modelo ficam como contratos, não como entrega.

## 1. Arquitetura

Três responsabilidades, um produto, o monorepo atual.

| Camada | Responsabilidade | Onde mora hoje | O que muda no Gate 2.0 |
|---|---|---|---|
| JARVIS | Interface: Agora, conversa, inbox, domínios, aprovações, fontes. Não decide política e não guarda segredo. | `apps/web` | Passa a ler a API no modo real. O modo DEMO continua nas fixtures e fica visualmente separado. |
| Victor OS | Briefing, propostas, fila de aprovação e regras. Não grava em provedor externo. | Regras hoje espalhadas na UI e nas fixtures | Vira serviço em `apps/api`: determinístico, com evidência por fato. Sem modelo de linguagem nesta etapa. |
| Victor Context Hub | Memória, proveniência, conectores, sincronização, retenção e auditoria. | Contrato `jarvis.demo.v1` e leitura de `fixtures/demo.json` | Persistência local, adaptadores e trilha de origem. O Calendar entra por um adaptador; os outros ficam com interface vazia. |

O que se reaproveita: Next.js 15.5, FastAPI 0.141, Pydantic, os oito domínios, o drawer de proveniência, os estados `mock | connected | stale | error | pending_approval`, o contrato versionado e a regra de que escrita externa continua desligada.

O que não se reaproveita como memória real: `localStorage` do Inbox, a lista crua de propostas na API e o fato de o navegador importar `fixtures/demo.json` direto. Isso permanece só no modo DEMO e nos testes.

### Alternativas de implantação

Recomendação para o Gate 2.0: **somente local, no computador do proprietário**. Sem porta pública, sem túnel e sem banco gerenciado.

| Opção | Custo estimado | Manutenção | Segurança |
|---|---|---|---|
| Local no Mac já em uso | R$ 0 de serviço. O custo é tempo de backup e atualização. | Alta atenção manual, baixa complexidade. Um processo `api` e um `web` em localhost. | A melhor fronteira desta fase: disco com FileVault, segredo fora do git, sem exposição de rede. O risco principal é o acesso físico e um backup sem cifra. |
| VPS próprio | Cerca de US$ 5 a 15 por mês, mais domínio se houver nome público. | Firewall, certificado, atualização de sistema e vigilância de login. | Exige autenticação forte antes do primeiro evento real. Um túnel ou porta aberta amplia o roubo de token. Não recomendado no 2.0. |
| Serviço gerenciado | Cerca de US$ 15 a 50 por mês em uso pessoal pequeno, conforme banco e tráfego. Valores de tabela mudam. | Menos servidor para cuidar, mais console e conta no provedor. | O token e a memória saem da máquina. Só faz sentido depois do modelo de ameaças de acesso remoto. Fora do 2.0. |

Google Calendar API, no volume de uma pessoa, não tem custo relevante de chamada. O projeto na nuvem do Google, se for criado no futuro, existe para o cliente OAuth, não para hospedar o JARVIS.

## 2. Identidade e segurança

Há um único proprietário. Não há multiusuário.

Autenticação proposta, ainda local:

- Sessão opaca, cookie `HttpOnly`, `SameSite=Lax`, `Secure` quando houver HTTPS.
- O segredo de sessão fica no chaveiro do sistema ou num arquivo cifrado fora do repositório, nunca no cliente e nunca no log.
- Sem sessão válida, a API real responde 401. O modo DEMO pode continuar aberto só em desenvolvimento, com cabeçalho e badge DEMO, e não lê a base real.

Autorização efetiva, separada de `domain_id`:

- `domain_id` continua sendo classificação de memória.
- A permissão mora numa concessão: quem, qual conector, qual escopo, quais calendários, quais domínios de destino, validade e revogação.
- O servidor filtra a consulta pela concessão e só depois aplica o filtro de domínio pedido pela interface.
- Um pedido “mostre o domínio pessoal” não devolve evento classificado como MedSyn ou MCID, mesmo que o título coincida.
- Calendário institucional não entra pela conta pessoal. Se um evento parecer institucional, fica em quarentena até decisão humana de classificação. Não há cópia automática para outro domínio.

Criptografia e credenciais:

- Disco cifrado é obrigatório e não substitui o cuidado com o token.
- O refresh token, quando existir no futuro, fica cifrado num cofre local. A chave não vai para o git.
- Logs registram nome de operação, código de erro e identificador opaco. Não registram título de evento, e-mail, token, código de autorização nem corpo de resposta do Google.
- Exportação e exclusão são ações explícitas, com confirmação.

## 3. Memória real

Banco inicial: SQLite, arquivo fora do git, em modo WAL. PostgreSQL fica para quando houver mais de um conector concorrente ou acesso remoto. Busca vetorial não entra no 2.0.

Tabelas alinhadas ao Blueprint: `sources`, `events`, `entities`, `relations`, `decisions`, `actions`, `preferences`, `audit_entries`, mais `sync_cursors` e `grants`. Todo evento real carrega origem, referência externa, instante observado, última verificação, confiança, sensibilidade, `domain_id` e validade.

Políticas:

- Retenção padrão proposta: eventos observados por 24 meses, salvo exclusão manual. A decisão é do proprietário.
- Exclusão apaga o evento local e a trilha que contenha texto do evento. A auditoria restante guarda só identificador e resultado.
- Backup: cópia cifrada do arquivo SQLite e do cofre, testada com restauração num banco vazio. Sem teste de restauração, o backup não conta.
- Sincronização incremental guarda o cursor. Se o provedor invalidar o cursor, faz-se leitura completa de novo e a interface mostra `stale` até terminar. Silêncio não significa “está em dia”.

Migração das fixtures:

- `fixtures/demo.json` e o schema `jarvis.demo.v1` permanecem para teste.
- A base real nasce vazia, com `dataset = real`.
- Nenhuma rotina copia DEMO para a base real.
- A interface não mistura os dois conjuntos na mesma lista. Trocar de modo é explícito e o modo real não usa o badge DEMO.

### Implementação delimitada C.1

O estado implementado e os seus limites estão documentados em [`docs/GATE2_0C_1_MEMORIA.md`](GATE2_0C_1_MEMORIA.md). C.1 materializa o armazenamento local vazio, modelos e consultas protegidas por sessão e concessão voláteis; não implementa o restante esquema futuro descrito nesta proposta, sincronização, backup ou qualquer fonte externa.

## 4. Primeira integração

Somente depois dos critérios da seção 7. Até lá, o adaptador de Calendar fala com um falso provedor em teste.

Desenho, ainda não construído:

- Escopos candidatos, a escolher pelo proprietário antes de existir cliente OAuth: `calendar.events.readonly` e, se a lista de calendários for necessária, `calendar.calendarlist.readonly`. Não usar escopo de escrita.
- Fluxo: código de autorização com PKCE, redirect só em `localhost`, consentimento mostrado no JARVIS antes do salto, conta pessoal única.
- Mapeamento calendário para `domain_id` é uma decisão humana por calendário, gravada na concessão. Sem mapa, o evento fica em quarentena e não aparece em domínio nenhum.
- Incremental: `syncToken` por calendário. Erro 410 dispara ressincronização e estado `stale` visível.
- Revogação: apagar o token local, marcar a fonte como revogada e parar o cursor. O proprietário escolhe se os eventos já copiados são mantidos ou apagados.
- Falhas de rede, 401 e relógio de 24 horas sem sucesso aparecem como `error` ou `stale`. A tela Agora não trata a ausência de resposta como “não há compromisso”.

Gmail e Drive não recebem cliente, escopo nem botão de conexão nesta proposta.

## 5. Evolução

Contratos para o futuro, sem implementação:

- Adaptador com `capabilities`, `scopes`, `sync`, `revoke` e `normalize`.
- O normalizador produz `Event` com proveniência. Gmail, no futuro, seria comunicação, não compromisso. Drive seria referência, não evento de agenda.
- A conversa continua com regras e fixtures no modo DEMO. No modo real, o Gate 2.0 responde só com fatos do banco e recusa pergunta que exigiria modelo de linguagem. Um provedor de modelo entra noutro gate, com orçamento, retenção de prompt e teste de injeção.

## 6. Modelo de ameaças

| Risco | Controle verificável |
|---|---|
| Token OAuth no repositório, no log ou no navegador | Busca automatizada por padrões de segredo no git. Teste de log que falha se o corpo do provedor aparecer. Token só no cofre do servidor. |
| Sessão roubada em localhost | Cookie opaco, curta duração, rotação na revogação. Sem token de provedor no JavaScript. |
| Vazamento entre domínios | Teste em que título cita outro domínio e a API devolve só a concessão daquele principal. Quarentena sem classificação. |
| Calendário institucional puxado pela conta pessoal | Lista de calendários conferida por humano antes do primeiro sync. Domínios MedSyn e MCID bloqueados por padrão. |
| Prompt injection quando houver texto de evento na conversa | No 2.0 a conversa real não interpreta instrução vinda do título do evento como comando. Texto de evento é dado, não ordem. |
| Ação externa acidental | Nenhum método de escrita no adaptador. Teste que a superfície pública não contém insert, update ou delete no Google. |
| Backup sem cifra ou restauração não testada | Ensaio de restauração com dado sintético antes de qualquer evento real. |
| Mistura DEMO e real | Consultas exigem `dataset`. Teste de integração falha se um identificador DEMO aparecer na base real. |
| Exposição por túnel ou porta pública | Fora do desenho. Qualquer pedido de túnel interrompe a entrega. |

## 7. Plano de execução

Estimativas são de trabalho focado de uma pessoa. Não são prazo de calendário. Cada incremento tem branch própria e pode ser revertido por não promover a flag ou por apagar a base local ainda vazia.

| Incremento | Entrega | Aceite | Esforço | Depende de |
|---|---|---|---|---|
| 2.0-A | Decisão humana desta proposta: hospedagem local, escopos candidatos, retenção e quais calendários jamais entram. | Registro assinado no documento de decisão. Sem código de provedor. | 0,5 dia | Aprovação desta proposta |
| 2.0-B | Sessão local e modelo de concessão. API real sem sessão responde 401. DEMO segue separado. | Testes de 401, cookie e concessão. Nenhum segredo no repo. | 3 a 5 dias | 2.0-A |
| 2.0-C | SQLite, migração, proveniência, backup e restauração com dado sintético. | Restauração conferida. DEMO não aparece na base real. | 4 a 6 dias | 2.0-B |
| 2.0-D | Adaptador falso de Calendar, cursor, estado stale às 24 horas e quarentena sem `domain_id`. | Testes de sync, 410, erro e isolamento dos oito domínios. | 4 a 6 dias | 2.0-C |
| 2.0-E | A interface lê a API no modo real e mantém o modo DEMO. | Playwright dos dois modos. Badge DEMO ausente no modo real. | 3 a 5 dias | 2.0-D |
| 2.0-F | Somente após novo aceite: cliente OAuth local, PKCE, cofre, consentimento e revogação. Ainda com conta de teste vazia ou calendário criado para ensaio, se o proprietário autorizar. | Escopos iguais aos aprovados. Revogação apaga o token. Log sem PII. | 5 a 8 dias | 2.0-E e nova autorização |
| 2.0-G | Primeira leitura da conta pessoal, calendários mapeados um a um. | Evento real visível com proveniência. Institucional não importado. Escrita externa inexistente. | 2 a 4 dias | 2.0-F e mapa de calendários |

Total aproximado antes de qualquer dado real: 15 a 23 dias de trabalho, incrementos A a E. A conexão em si são os incrementos F e G.

Reversão: até E, apagar o arquivo SQLite local volta ao protótipo. A partir de F, a reversão inclui revogar o cliente no Google e apagar o cofre. A tag `gate1-accepted-v0.1` permanece o retorno conhecido.

### Critérios antes de conectar dados reais

Todos precisam estar verdes ao mesmo tempo:

1. Esta proposta aprovada por escrito, com hospedagem local e escopos exatos.
2. API real inacessível sem sessão.
3. Concessão de servidor distinta de `domain_id`, com teste de vazamento entre os oito domínios.
4. Base real vazia e impossível de misturar com DEMO.
5. Backup cifrado restaurado em ensaio sintético.
6. Adaptador falso cobrindo sync, falha, cursor inválido e stale de 24 horas.
7. Interface sem badge DEMO no modo real e sem caminho de escrita ao Google.
8. Logs de um ensaio sem título, e-mail, token ou código OAuth.
9. O proprietário indica a conta pessoal e o mapa calendário para domínio. MedSyn e MCID ficam de fora.
10. Novo aceite humano específico para criar o cliente OAuth. Este documento não é esse aceite.

## 8. Decisões pendentes de aprovação específica

Este documento não aprova as três decisões abaixo. Cada uma continua aberta até um aceite humano separado. Nenhuma delas autoriza criar cliente OAuth, conectar conta ou copiar dado real.

| Decisão | Estado | O que este texto apenas registra |
|---|---|---|
| Retenção dos eventos observados | Pendente | Há uma hipótese de 24 meses, com exclusão manual. Não está escolhida. |
| Escopos OAuth | Pendente | Os candidatos são `calendar.events.readonly` e, se a lista de calendários for necessária, `calendar.calendarlist.readonly`. O escopo exato não foi escolhido. Escopo de escrita está fora. |
| Política de revogação | Pendente | A revogação apaga o token local e para a sincronização. Ainda não está decidido se os eventos já copiados são mantidos ou apagados. |

## 9. Decisões do proprietário

1. Confirmar hospedagem só local no Gate 2.0.
2. Aceitar estreitar a primeira fonte para Calendar somente leitura, em vez de Calendar e Gmail juntos.
3. Escolher os escopos exatos antes de existir qualquer cliente.
4. Definir retenção e se a revogação apaga os eventos já copiados.
5. Dizer quais calendários pessoais existem e qual `domain_id` cada um recebe.
6. Confirmar que MedSyn, MCID e qualquer agenda institucional ficam fora desta conta.
7. Autorizar, num momento posterior e separado, a criação do cliente OAuth.
