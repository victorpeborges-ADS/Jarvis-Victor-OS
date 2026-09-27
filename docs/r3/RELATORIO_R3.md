# Relatório da sprint JARVIS R3

**Data:** 26/09/2026

**Branch:** `feat/jarvis-unified-r3-2026-09-26`
**Estado de G5:** auditoria independente pendente; este relatório não declara aceite formal.

## Baseline e preservação

- Baseline R2 congelado: `bb6b78a8631b8e25f18d175178270b6a957fbf86`.
- Main esperada: `8e7c09bb303deb6fe444a3a455961519a5f414d2`.
- A branch exclusiva R3 foi derivada do baseline R2. A validação final de ancestralidade e limpeza está registrada no handoff da sprint.
- A main esperada é ancestral do baseline R2; R3 inicia exatamente em `bb6b78a`. Nenhuma integração entre branches foi feita.
- A worktree R2 original, a main, a manutenção `a6cd0fffc4207a10462bef853a8994a8fd037c12` e seus arquivos permaneceram intocados.
- Os quatro arquivos não rastreados da worktree original foram preservados e conferidos por SHA-256. A cópia de auditoria já estava suja antes da sprint e não foi alterada.

## Auditoria Grok e objetivo

O pacote no Google Drive foi lido integralmente, com atenção a `02b-achados-unificados.md`, `05-ux-a11y-editorial.md`, `09-backlog-correcoes.md` e `10-guia-reproducao.md`.

R3 implementa os achados P1 de navegação, controles e acessibilidade; padroniza a linguagem de produto em português brasileiro; move detalhes operacionais para áreas técnicas; e resolve os achados P2 de rótulos, estados, tipografia, hierarquia e pluralização. Também fecha a corrida entre revogação e leituras de Missões/revisões, atualiza os probes adversariais e acompanha o novo ID após revisão de artefato.

## Entregas

### Produto e acessibilidade

- Conversa ficou disponível diretamente na navegação mobile e no atalho universal do cabeçalho. As sugestões abrem a conversa já preenchida e não são enviadas automaticamente.
- A navegação usa os mesmos rótulos para Aprovações e Integração local; a área técnica aparece como seção secundária.
- Exportar exemplos baixa um JSON. O pedido de remoção responde claramente que o registro vale somente para esta tela e que não há dados pessoais armazenados.
- Estados de demonstração, atualização, atraso e erro usam mensagens compreensíveis. Respostas de engenharia ficam em divulgações secundárias.
- Botões, links de ação e seletores ganharam alvos maiores; filas passaram a usar pluralização correta; metadados extensos de fontes ficaram recolhidos.
- A interface continua fictícia e local. Nenhuma conta externa, API pública ou dado pessoal foi habilitado.

### Segurança e modelo de ameaças

O modelo local, ativos, fronteiras, atores, controles, ordem de locks e riscos restantes estão em [THREAT_MODEL_LOCAL.md](THREAT_MODEL_LOCAL.md).

As leituras de lista e detalhe de Missões e revisões agora confirmam sessão e escopo mantendo `_grant_lock` durante a leitura SQLite e a montagem do snapshot. A ordem obrigatória é `_grant_lock` → SQLite. Assim, se a revogação vence, uma leitura posterior recebe 403; se a leitura vence, o snapshot autorizado é copiado antes de a revogação seguir. O backend mantém a rejeição de decisões com ID/versão antigos; o E2E agora segue o novo ID devolvido por `revise`.

Os oito probes adversariais cobrem duas ordens concorrentes para quatro leituras: lista/detalhe de Missões e lista/detalhe de revisões. A janela restante é de transporte: uma resposta cujo snapshot já foi autorizado pode chegar ao cliente depois que a revogação aguardada conclui. O modelo não promete apagar bytes já preparados.

Sessões e concessões continuam voláteis e locais, válidas em um processo. A sprint não introduz autenticação remota, multiworker, rede pública, OAuth, dados pessoais ou cifragem do SQLite.

### Evidência visual e editorial

A captura cobre nove rotas em 320, 390, 767, 768, 769, 1024 e 1440 px, além do menu Mais a 390 px: 63 capturas de rota por fase e uma captura do menu. Os arquivos JSON registram largura, overflow, alvos pequenos e erros de página.

| Tela | R2 antes | R3 depois |
|---|---|---|
| Agora, 390 px | [captura](captures/before/agora-390.png) | [captura](captures/after/agora-390.png) |
| Agora, 1440 px | [captura](captures/before/agora-1440.png) | [captura](captures/after/agora-1440.png) |
| Aprovações, 390 px | [captura](captures/before/aprovacoes-390.png) | [captura](captures/after/aprovacoes-390.png) |
| Fontes, 390 px | [captura](captures/before/fontes-390.png) | [captura](captures/after/fontes-390.png) |
| Integração, 320 px | [captura](captures/before/integracao-320.png) | [captura](captures/after/integracao-320.png) |
| Menu Mais, 390 px | [captura](captures/before/mais-390.png) | [captura](captures/after/mais-390.png) |

Resultado da inspeção depois das correções: **63/63 telas sem overflow horizontal, 0 erros de página e 0 alvos de ação abaixo de 24×24 px**. A captura visual também confirmou a mudança de navegação entre 767 e 768 px e a apresentação em desktop a partir de 769 px.

Índices completos: [R2 antes](captures/before/inspection.json) e [R3 depois](captures/after/inspection.json).

## Arquivos alterados

- API: `apps/api/local_security.py`, `apps/api/mission_api.py`, `apps/api/review_api.py`, `apps/api/test_review_api.py` e novo `apps/api/test_mission_read_revocation_races.py`.
- Web: páginas de Agora, Conversa, Inbox, Domínios, Fontes, Aprovações, Missões e Integração; cabeçalho, navegações, primitives e integração local; testes Vitest e Playwright ajustados à linguagem e ao fluxo versionado.
- Evidências: `docs/r3/THREAT_MODEL_LOCAL.md`, `docs/r3/captures/before/`, `docs/r3/captures/after/` e este relatório.

## Comandos e resultados

Todos os comandos foram executados com o prefixo `rtk` na worktree R3.

| Comando | Resultado |
|---|---|
| `uv run --locked pytest -q` em `apps/api` | **225 passaram**, 0 falhas; 2 avisos de depreciação de dependências; exit 0 |
| `uv run --locked pytest -q test_mission_read_revocation_races.py test_mission_auth_races.py test_review_api.py test_mission_import_identity.py` | **45 passaram**, 0 falhas; 1 aviso de depreciação; exit 0 |
| `npm test` em `apps/web` | **66/66 passaram** |
| `npm run typecheck` em `apps/web` | passou |
| `npm run lint` em `apps/web` | passou sem erros; Next informa que `next lint` será removido no Next 16 |
| `npm run build` em `apps/web` | passou |
| `npm test`, `npm run lint`, `npm run build` em `apps/mobile` | **2/2 testes**, lint e build passaram |
| `npm run e2e -- --retries=0` — rodada 1 | **62 passaram, 2 ignorados pela configuração desktop/mobile**, 0 retries; exit 0 |
| `npm run e2e -- --retries=0` — rodada 2 | **62 passaram, 2 ignorados pela configuração desktop/mobile**, 0 retries; estado final do Playwright `passed`, sem testes falhos |

O runner E2E oficial iniciou somente a API em loopback, usou SQLite sintético temporário e removeu a base ao encerrar cada rodada.

## Riscos residuais

- API e banco permanecem locais, sem cifragem nesta sprint; quem controla a conta do sistema operacional pode ler ou alterar os arquivos.
- Sessões e concessões em memória não são compartilháveis entre processos. Multiworker, acesso remoto, túnel, OAuth, conexão real e deploy estão fora do escopo.
- Uma leitura que obteve o lock primeiro pode ter sua resposta transportada após o término da revogação; novas leituras iniciadas depois da revogação são recusadas.
- A regressão foi realizada apenas com fixtures e bancos sintéticos temporários. G5 continua pendente de auditoria independente e de decisão formal.

## Pendências e próximo gate

- Auditoria independente da branch R3 e decisão humana sobre o encerramento formal de G5.
- Eventos de dia inteiro, integração Calendar real, OAuth, Gmail, Drive, LLM, acesso remoto e deploy exigem contrato e autorização específicos.
- Nenhum merge, push, tag, deploy, conexão de conta real ou serviço persistente foi executado.
