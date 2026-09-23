# JARVIS — Pacote de prompts executáveis
**23/09/2026 · Leia também `JARVIS_Blueprint_v0.1.md`.**

Os prompts são intencionalmente sequenciais. Não execute Build antes de revisar os resultados do Plan, nem ative conectores reais antes de passar pelo protótipo mock.

## Prompt 0 — OpenCode Plan: auditoria local sem escrita destrutiva

> Você é o arquiteto de implementação inicial do JARVIS, produto unificado composto por interface JARVIS, motor de planejamento Victor OS e memória Victor Context Hub. Leia `JARVIS_Blueprint_v0.1.md` integralmente. Primeiro identifique a versão instalada do OpenCode e valide a sintaxe de suas permissões usando documentação apropriada à versão — não suponha equivalência entre V1 e V2. Trabalhe inicialmente em modo Plan, somente leitura do código existente.
>
> Escopo: auditar apenas os diretórios de projeto explicitamente autorizados neste workspace. Descubra se já existe JARVIS, Victor Context Hub, Victor OS ou infraestrutura reaproveitável. Examine `package.json`, manifests Python, git remotes/branches, README, arquitetura, testes e infraestrutura. Não leia conteúdo de `.env`, chaves, tokens, cookies, sessões ou outros arquivos secretos; registre apenas nomes de variáveis necessárias. Não varra `/Users/vic` inteiro. Não modifique MCID, MedSyn, CRIVO ou SOFF. Não faça push, deploy, network tunnel, instalação global, limpeza de git ou alterações em produção.
>
> Entregue: (1) inventário factual com evidências/caminhos; (2) recomendação entre aproveitar repo existente ou criar novo monorepo pessoal `jarvis`, explicitando trade-offs; (3) mapa de contexto e proveniência; (4) modelo de dados v0.1; (5) contratos API e limites de permissão; (6) wireframes textuais desktop/mobile e três jornadas; (7) backlog vertical em tarefas pequenas e testáveis, dependências e estimativas em ordem relativa; (8) riscos e decisões que exigem validação humana; (9) gate de aceite do protótipo.
>
> Não invente integrações nem afirme funcionalidades implementadas sem provas. Entregue o plano no chat; somente após autorização, escreva os arquivos de documentação no repositório selecionado. Ao final, pare antes do Build.

## Prompt 1 — OpenCode Build: fundação e interface em fixtures

> Use o blueprint e o relatório de auditoria aprovados como contrato. Abra branch de feature ou worktree dedicado; preserve todos os arquivos preexistentes sem reset/clean/stash destrutivo. Crie ou complete `AGENTS.md` único e conciso com arquitetura, comandos reais de build/teste, política de dados, gates de ações e Definition of Done. Gere o esqueleto frontend Next.js/React/TypeScript e backend FastAPI APENAS se a auditoria confirmar ser a opção apropriada.
>
> Primeiro implemente design tokens, componentes base acessíveis e uma experiência navegável utilizando dados DEMO explicitamente sinalizados. Páginas: Agora, Conversa JARVIS, Inbox, Domínios, Aprovações e Origens/Privacidade. Desktop com foco editorial, mobile-first, navegação simples, comando universal de texto e placeholder honesto de voz. Não crie um dashboard genérico. A tela Agora deve mostrar próximo compromisso, até três decisões úteis, timeline compacta, status de conectores e botão de captura rápida. Cada recomendação deve abrir um drawer de fontes e explicação. Estados loading/empty/error/stale/mocks obrigatórios.
>
> Implemente as três jornadas com fixtures: briefing diário, conflito de agenda e captura rápida de ideia de CRIVO. Evite chamadas reais a Gmail/Calendar/Drive nesta fase. Garanta keyboard navigation, foco visível, reduced motion, responsividade, tipografia legível, contraste e testes básicos de acessibilidade. Crie Storybook ou ComponentLab se o custo for justificado; documente decisões de design. Inclua Playwright E2E para desktop e mobile, testes unitários, lint, typecheck e build reproduzíveis.
>
> Handoff obrigatório: commit de feature, lista de arquivos mudados, screenshots desktop/mobile, instruções reais de execução, demonstração das três jornadas, resultados de testes, limitações identificadas e itens bloqueados. PARE no fim do Gate 1. Não implemente autenticação improvisada, conexões de produção ou ações externas.

## Prompt 2 — OpenCode Build: primeiro fluxo real somente leitura

> Só executar após o protótipo aprovado visualmente e gate de arquitetura do Codex. Crie branch isolada, faça threat model curto, configure OAuth de menor privilégio para Calendar e Gmail APENAS na conta pessoal explicitamente autorizada. Não solicitar permissões de edição ou escopos desnecessários. Secrets em armazenamento local protegido, nunca no git/logs/cliente. Integre via adapters tipados, com status mock/connected/stale/error e paginação/retentativas conservadoras. Implemente pipeline normalização->Event com proveniência->ranking explicável->briefing. Prioridades só a partir de fontes autorizadas ou preferências explícitas; LLM opcional não pode criar fatos.
>
> Cobrir o caso de calendários múltiplos, e-mail promocional, link suspeito, fonte indisponível, data/timezone America/Sao_Paulo e compromissos antigos já concluídos. Adicionar testes de integração com mocks; não usar dados reais em snapshots. Registrar histórico auditável minimizado, exportação e restauração. A escrita em Google Calendar/Gmail permanece DESATIVADA. Gere relatório com escopos efetivos, casos testados, URLs de documentação e perguntas de segurança. PARE no Gate 2.

## Prompt 3 — Codex: auditoria e depuração de alta criticidade

> Audite o JARVIS após os Gates 1 e 2 como revisor independente. Leia `AGENTS.md`, blueprint, report de auditoria, commits e testes. Inspecione: fronteiras de domínio e permissão, OAuth, storage de credenciais, XSS/CSRF/CORS, SSRF em URLs fornecidas, SQL injection, autenticação/autorização, idempotência, races de sync, duplicatas, timezone, eventos obsoletos, proveniência de fatos, falhas dos provedores, backups/restore, logs PII e UX de aprovação. Para cada falha: severidade, reprodução, arquivo/linha, consequência e teste de regressão proposto. Não confunda melhorias cosméticas com vulnerabilidades. Depois da revisão, corrija os itens críticos e altos em commits delimitados, valide scripts reais e produza checklist de liberação. Não executar deploy ou abrir conectores de escrita sem autorização.

## Prompt 4 — Cursor: design/UX e depuração visual

> Trabalhe sobre o build aprovado. Objetivo: transformar um app funcional em interface de uso diário extraordinariamente clara, rápida e acessível. Não altere contratos ou política de autorização sem alinhamento. Investigue em desktop e mobile as jornadas Agora, briefing, ação pendente, captura rápida, perguntar ao JARVIS, trocar domínio, verificar evidência, aprovar/rejeitar. Execute revisão de hierarquia visual, microcopy em PT-BR, estados vazios/erro/stale, skeletons, touch targets, foco/teclado/leitor de tela, performance perceptual, transições acessíveis e modo claro/escuro.
>
> Entregue screenshot BEFORE/AFTER por jornada, rationale baseada em tarefas reais, componentes compartilhados, testes Playwright por viewport e inventário de bugs ordenado por impacto. Priorize menos cliques e menos carga cognitiva; não copie literalmente identidades visuais de outros produtos. A tela Agora deve permanecer legível em 5 segundos e uma nota deve ser capturável em no máximo duas interações. Execute ao menos dois ciclos internos de inspeção->ajuste->teste->screenshot antes da entrega. Documente oportunidades, mas não acrescente features fora do escopo aprovado.

## Prompt 5 — QA de aceitação multidisciplinar

> Como equipe de revisão, verifique que todas as ações externas permanecem sujeitas a aprovação; status mock nunca parece real; todas as conclusões críticas incluem origem; domínios sensíveis não vazam; principais fluxos são navegáveis apenas por teclado; cenário offline/stale degrada de modo honesto; as três jornadas têm E2E passando. Faça auditoria adversarial e manual com 20 cenários edge cases relevantes à vida real (MedSyn/MCID, academia, Bruna, viagens, candidatura, orçamento, prazos, alteração de timezone, notificações repetidas). Classifique cada resultado PASS/FAIL/BLOCKED com evidência. Não anuncie Gate aprovado se existirem bugs críticos, testes falhando ou apenas simulação sem rótulo.

## Handoff padronizado para todos os agentes
O agente deve responder sempre com: BASELINE (branch/commit), OBJETIVO, ARQUIVOS ALTERADOS, DECISÕES, COMANDOS EXECUTADOS, TESTES PASS/FAIL/BLOCKED, CAPTURAS/DEMOS, RISCOS RESIDUAIS, PENDÊNCIAS DE AUTORIZAÇÃO, PRÓXIMO GATE. Nunca dizer que testou algo que não rodou. Se não tiver acesso ao ambiente local, explicitar quais verificações foram apenas estáticas.
