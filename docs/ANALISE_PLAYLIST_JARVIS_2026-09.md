# Avaliação da playlist “jarvis” — ideias para o JARVIS

**Data:** 24/09/2026  
**Playlist:** [jarvis — Victor Borges](https://www.youtube.com/playlist?list=PLUjjNwKbtFLc)  
**Cobertura:** 29 vídeos  
**Baseline do repositório:** `feat/gate2.0-e-integracao-web-api`, commit `e648e92`.

## Síntese

A playlist reforça a direção já definida para o JARVIS: memória com contexto, respostas ligadas a fontes, interface conversacional e automações limitadas. A maior parte das demonstrações usa produtos específicos — Claude, ChatGPT, Hermes, n8n, Telegram, WhatsApp, Obsidian e ferramentas de voz — e não representa arquitetura que devamos copiar.

As contribuições mais úteis que ainda não aparecem como capacidades explícitas no roadmap são:

1. **Ciclo de vida do conhecimento:** separar fatos e notas escritos pela pessoa, material de origem e artefatos produzidos pela IA; revisar, corrigir, aprovar ou expirar os derivados.
2. **Montagem de contexto por tarefa:** entregar à conversa um conjunto pequeno e rastreável de fontes relevantes para o projeto/domínio, em vez de despejar histórico ou memória indiscriminadamente.
3. **Catálogo de skills/runbooks:** fluxos reutilizáveis com entradas, saídas, fontes e permissões declaradas, testados com dados sintéticos e submetidos às mesmas aprovações do restante do sistema.
4. **Observadores somente leitura:** tarefas agendadas que comparam fontes autorizadas e avisam apenas quando há mudança relevante, sempre com evidência e estado de sincronização visíveis.
5. **Preferências de interrupção:** horário silencioso, modo de reunião, canal, urgência, adiamento e limite de notificações para qualquer proatividade futura.

Esses itens são propostas para o backlog, não decisões aprovadas nem autorização para começar conectores reais. O próximo passo registrado continua sendo a auditoria independente do Gate 2.0-E.

## Método e limites da análise

Conferi a lista completa e os títulos dos 29 vídeos. Para a análise usei descrições, capítulos, resumos estruturados do YouTube e as transcrições que estavam disponíveis. Li a transcrição completa dos vídeos 1 e 8 e trechos do vídeo 5; pedi ao recurso de resumo do próprio YouTube sínteses adicionais para os vídeos 5, 14, 20, 23 e 27. Não assisti integralmente às aproximadamente onze horas de vídeo nem validei independentemente as alegações promocionais, preços, modelos ou resultados apresentados.

O vídeo 24, “Por que abrir um chat novo para tudo te faz perder tempo”, está marcado como conteúdo exclusivo para membros. Para ele usei apenas o título, a descrição e os capítulos que estavam públicos; não acessei conteúdo restrito. Por isso, a avaliação daquele item é parcial.

“Aderência” abaixo significa compatibilidade com a direção do produto; não significa funcionalidade implementada, segurança validada ou autorização para integrar um serviço.

## O que o projeto já cobre

O estado atual é mais restrito que as demonstrações da playlist:

- A interface DEMO cobre Agora, Conversa, Inbox, Domínios, Aprovações e Fontes/Privacidade. O modo API local do Gate E fala somente com o Calendar simulado e um banco sintético; os conjuntos DEMO e API permanecem separados.
- C.1 já registra fontes, eventos, entidades, relações, decisões e auditoria com proveniência. C.2 cobre backup cifrado e restauração isolada de bancos sintéticos.
- O Gate D exercita sincronização, classificação explícita, grants e estados de fonte no Calendar fictício. A integração web/API do Gate E ainda aguarda auditoria independente.
- O blueprint já prevê Calendar somente leitura como primeira integração real, Gmail em etapa posterior, Drive em outra onda, n8n para rotinas limitadas, LLM opcional em gate próprio, escrita supervisionada e voz/PWA refinadas.
- Proveniência, separação de domínios, estados `mock | connected | stale | error | pending_approval`, revisão humana e ausência de autonomia sem scheduler já são princípios explícitos.

Não estão implementados/autorizados: OAuth ou provedores Google reais, Gmail, Drive, Telegram/WhatsApp, LLM, voz, controle do computador/câmera, notificações em background, dados pessoais/institucionais ou escrita externa. A proposta de arquitetura estreita a primeira fonte real para Calendar somente leitura; o Gate E não amplia esse escopo.

## Fichas dos vídeos

| # | Vídeo | Ideia principal observada | Aderência e leitura para o JARVIS |
|---|---|---|---|
| 1 | [Criei um JARVIS pra mim e cancelei todas as minhas IAs](https://www.youtube.com/watch?v=gGFQU2CsAqk) | Abacus/DeepAgent, roteamento de modelos, análise de despesas, compromissos, treino, voz e criação de painéis a partir de arquivos. | **Alta.** Assistente contextual e análise de entradas reforçam o produto. Roteamento de modelos já aparece no blueprint; finanças e saúde continuam fora dos dados permitidos sem autorização específica. |
| 2 | [Como construí o JARVIS do Homem de Ferro no n8n](https://www.youtube.com/watch?v=vTIq4pUR7o0) | Fluxos n8n, voz ElevenLabs, Gmail, Calendar e Airtable para agenda, e-mails e contatos. | **Alta, futura.** n8n e integrações limitadas já estão no blueprint. A demonstração não muda o gate atual de somente simulação. |
| 3 | [Como construí um JARVIS pessoal que sabe tudo sobre meu negócio](https://www.youtube.com/watch?v=sl-ByvLRAP0) | Claude Code com contexto empresarial, voz, redes sociais e campanhas. | **Alta.** Contexto por projeto/domínio é aderente. Campanhas e redes sociais são exemplos de integrações, não fontes aprovadas para o JARVIS. |
| 4 | [Build JARVIS 3.0: Voice, Memory & PC Control](https://www.youtube.com/watch?v=qw16ascMH4Y) | Assistente local em Python/Gemini com voz e controle do computador. | **Parcial.** Voz está prevista no Gate 5; controle geral do computador não consta no roadmap e ampliaria muito o risco de acesso. |
| 5 | [My AI Called Me During a Meeting](https://www.youtube.com/watch?v=zdnijkAbknA) | Demonstra chamadas, Calendar, Telegram, busca em vault, troca de modelo, tela e visão por câmera. | **Parcial.** Sugere política de disponibilidade e interrupção para proatividade futura. Ligações, câmera, GUI e escrita em serviços ficam fora do escopo atual. |
| 6 | [Como eu uso o Claude pra tocar minha empresa inteira](https://www.youtube.com/watch?v=3cUQxnCMD2Y) | “Segundo cérebro” organizado em contexto, memória e ação, ligado a tarefas e métricas empresariais. | **Alta.** Corrobora a arquitetura Context Hub/OS e reforça contexto de projeto; não substitui fontes oficiais nem justifica copiar dados empresariais para a memória pessoal. |
| 7 | [Como realmente criar um segundo cérebro com IA](https://www.youtube.com/watch?v=tNjhgEof8UI) | Estruturar arquivos Markdown, histórico e skills em um espaço de trabalho do agente. | **Alta.** O padrão de workspace e artefatos persistentes é útil; o JARVIS ainda não especifica ciclo de vida distinto para notas humanas e saídas da IA. |
| 8 | [Segundo cérebro com IA: Claude Code + Obsidian](https://www.youtube.com/watch?v=8NOxb2WV95I) | Separa conhecimento autoral, ambiente de trabalho da IA e fluxo integrado; propõe entrada → transformação → saída → feedback; recomenda revisão e limpeza, sem deixar a IA sobrescrever notas permanentes. | **Alta e muito útil.** É a contribuição mais concreta: acrescentar staging para saídas da IA, autoria/revisão explícitas e manutenção periódica da memória. O modelo atual tem proveniência, mas não descreve essas etapas de conteúdo. |
| 9 | [Como transformei o Claude no meu assistente pessoal](https://www.youtube.com/watch?v=z4eoQX0DFf8) | IA para organização mental e apoio à decisão, preservando pensamento crítico e voz da pessoa. | **Parcial.** Reforça “humano no comando”, já princípio canônico; não é funcionalidade nova por si só. |
| 10 | [Agentes de IA: o que são e como trabalhar com eles](https://www.youtube.com/watch?v=wxD8MaD0xXk) | Agentes observam ambiente, decidem, usam ferramentas e podem ser orquestrados. | **Parcial.** É referência conceitual. Não justifica múltiplos agentes com escrita autônoma; o contrato do projeto exige limites e impede disputa por fontes. |
| 11 | [Hermes Agent: curso completo](https://www.youtube.com/watch?v=vZEp2sLGotk) | Hermes em VPS, memória persistente e integrações MCP. | **Parcial.** Memória e adapters conversam com a arquitetura; VPS, MCP amplo e autonomia não estão aprovados. |
| 12 | [Substitua sua secretária por esse agente de IA](https://www.youtube.com/watch?v=BDY-k3Mv6ZQ) | n8n e multiagentes para e-mail, calendário, contatos, pesquisa e criação de conteúdo. | **Alta, futura.** Mostra um padrão de workflow; criação/envio e integração real continuariam sujeitos a aprovação. |
| 13 | [Agente de IA é coisa do passado; agora eu só uso skills](https://www.youtube.com/watch?v=h_l8wCr7M2Q) | Playbooks reutilizáveis com instruções e scripts para funções e documentos específicos. | **Alta.** Inspira um catálogo de skills testáveis com escopo e permissões declarados; isso não existe como capacidade explícita no roadmap. |
| 14 | [Zero reais: tenha seu JARVIS particular](https://www.youtube.com/watch?v=149-j75zadY) | Bot Telegram local, long polling, acesso restrito por ID do proprietário, processos locais e Obsidian como persistência. | **Parcial.** A allowlist e o controle de acesso são bons padrões se algum canal de mensagem vier a ser considerado. Telegram e upload de conversas para serviços externos não estão no roadmap. |
| 15 | [I Built JARVIS with Claude Code](https://www.youtube.com/watch?v=Acw0NtkyNtM) | Integra Gmail/Calendar, chamadas, notas fiscais, voz/mensagens e leitura da tela. | **Parcial.** Reitera conectores e captura multimodal, mas não acrescenta algo pronto para o gate atual; chamadas e controle da tela são inadequados para iniciar agora. |
| 16 | [JARVIS Voice Agent com LiveKit](https://www.youtube.com/watch?v=Fhm8goKN6rM) | Agente de voz em tempo real, tools e interface web com LiveKit/Gemini. | **Parcial.** Detalha uma possível implementação do Gate 5; a decisão de arquitetura deve ocorrer só quando o contrato de voz for aprovado. |
| 17 | [I Built JARVIS with GPT-6 Astra](https://www.youtube.com/watch?v=mitzci4FsOg) | Voz em tempo real, monitoramento de tela e ferramentas específicas para tarefas pessoais/empresariais. | **Parcial.** Mesma direção multimodal; “monitoramento de tela” não está previsto e requer threat model próprio. |
| 18 | [Quatro agentes para automatizar o trabalho](https://www.youtube.com/watch?v=zXxktjZ7s34) | Papéis para organizar projetos, produzir documentos, auditar fontes e ensaiar negociações. | **Parcial.** A ideia mais segura é converter os papéis em skills com saídas revisáveis, em vez de agentes independentes com autoridade. |
| 19 | [Como automatizar qualquer tarefa com Claude](https://www.youtube.com/watch?v=M82KCVOlGwA) | Processar documentos financeiros, consolidar planilhas e enviar relatórios por e-mail. | **Parcial.** Pipeline de transformação e relatório é útil; dados financeiros e envio de e-mail estão sujeitos às fronteiras de domínio e aprovação, e não são parte do gate atual. |
| 20 | [Novo Modo Agente do ChatGPT](https://www.youtube.com/watch?v=IvCSMNmporw) | Pesquisa web, relatórios, slides, acompanhamento de projetos e monitoramento diário de mercado/notícias. | **Alta, futura.** A oportunidade menos coberta pelo roadmap é um observador somente leitura com scheduler real, comparação entre execuções, evidência e alerta apenas por mudança. |
| 21 | [ChatGPT Work na prática: 1.400 ferramentas](https://www.youtube.com/watch?v=ZimUHhHd2Fs) | Projetos em pastas, instruções em `agents.md`, conectores Notion/Drive e tarefas agendadas. | **Alta.** Pastas/contexto e instruções canônicas já têm equivalentes no repositório; os conectores seguem aguardando autorização. |
| 22 | [Conheça o novo ChatGPT Work](https://www.youtube.com/watch?v=Yw9B0sQyd9A) | Assistente atuando no computador, gerando apresentações/painéis e executando rotinas no navegador. | **Parcial.** Reforça geração de artefatos, mas controle de navegador/computador e rotinas externas não devem ser presumidos no JARVIS. |
| 23 | [Transforme sua rotina com Manus AI e ChatGPT](https://www.youtube.com/watch?v=S2nU4Cxr6l4) | Cadeia de agentes para pesquisa e conteúdo, ferramentas criativas e assistente Dola via WhatsApp. | **Parcial/baixa.** Reutilizar um workflow de pesquisa pode caber em skills; marketing, WhatsApp e automação comercial não são o foco do produto. |
| 24 | [Por que abrir um chat novo para tudo te faz perder tempo](https://www.youtube.com/watch?v=UMN2pPJwbV4) | A descrição e capítulos públicos citam engenharia de contexto: instruções, histórico, memória, documentos, projetos e conectores, além do risco de contexto excessivo. Vídeo exclusivo para membros. | **Alta, análise parcial.** Sustenta a proposta de montar um pacote contextual por projeto/tarefa, com limite de tamanho e referências rastreáveis; o conteúdo integral não estava acessível. |
| 25 | [Como colocar o Codex para trabalhar na sua empresa](https://www.youtube.com/watch?v=9R0_9p3ItSI) | Codex com ferramentas Google/GitHub/Notion, plugins e instruções para tarefas empresariais. | **Alta.** Confirma valor de ferramentas especializadas e contexto de projeto; o JARVIS já prevê adapters, e a demonstração não amplia as permissões do repositório. |
| 26 | [GPT Astra + Obsidian](https://www.youtube.com/watch?v=4zEmPhiRAaw) | Arquivos locais, histórico e relações entre notas para dar contexto à IA. | **Alta.** Reflete Context Hub e relações/proveniência que já estão no modelo; não justifica adotar Obsidian como fonte de verdade adicional. |
| 27 | [Eu não esperava que ele fizesse isso](https://www.youtube.com/watch?v=0LtdXQ_deUA) | Pesquisa baseada em referências científicas e geração de vídeo educativo e modelo 3D interativo. | **Baixa para o núcleo.** Pode inspirar relatórios ou artefatos derivados de fontes citadas, mas vídeo/3D é extensão de produto, não prioridade do JARVIS. |
| 28 | [Skills no Claude: 7 que mudam sua produtividade](https://www.youtube.com/watch?v=zo-SzqVj24o) | Skills para documentos, PDFs, planilhas e padronização de layouts/templates. | **Alta.** Fortalece o catálogo de skills e templates reutilizáveis; saídas devem ser drafts e não substituir documentos de origem. |
| 29 | [Hermes: 5 casos de uso](https://www.youtube.com/watch?v=cdQ40jNz6Ok) | Hermes em VPS com Telegram, Gmail e Google Cloud para tarefas autônomas. | **Parcial.** Repete o padrão de integrações e memória; não é novo para o roadmap de adapters e permanece fora do escopo de execução atual. |

## Ideias novas para o backlog

| Prioridade proposta | Ideia | Evidência na playlist | Diferença em relação ao roadmap | Como adaptar ao JARVIS com segurança |
|---|---|---|---|---|
| **P1 — especificar após auditoria E** | **Ciclo de vida de conhecimento e área de trabalho da IA** | Vídeos 7, 8 e 26 | O projeto já tem proveniência, decisões, auditoria e retenção conceitual; não define claramente estados de notas humanas, material importado, rascunhos de IA e conteúdo aprovado. | Classificar cada artefato como autoral, referência, derivado ou decisão. A IA cria em staging; não sobrescreve conhecimento autoral. Exigir revisão e vínculo com fontes antes de promover. Incluir revisão de obsolescência, duplicatas e limpeza. |
| **P1 — especificar antes do LLM** | **Pacote de contexto por domínio/projeto/tarefa** | Vídeos 8, 24 e 26 | O Context Hub e a busca aparecem no blueprint, mas não há contrato para escolher o que entra em cada conversa, evitar excesso e mostrar o que foi omitido. | Montar primeiro de forma determinística com fontes autorizadas, recência, domínio e validade. Exibir referências usadas, data de verificação e lacunas. Só testar busca semântica se um conjunto sintético provar ganho sobre busca convencional. |
| **P1 — protótipo com dados sintéticos** | **Catálogo versionado de skills/runbooks** | Vídeos 7, 11, 13, 18 e 28 | O blueprint menciona n8n e adapters, mas o produto não tem um catálogo formal de receitas operacionais. | Cada skill declara propósito, gatilho, entradas/saídas, ferramentas, domínio permitido, efeito colateral, versão e fixture de teste. Executar primeiro como leitura ou geração de draft; pedir confirmação para qualquer ação externa. Não executar scripts arbitrários fornecidos por vídeos. |
| **P2 — somente depois de scheduler real e fonte autorizada** | **Observadores de mudanças somente leitura** | Vídeos 1, 2 e 20 | O roadmap prevê sincronização e estados de fonte, mas não um produto de monitoramento configurável de temas/projetos com comparação entre execuções. | Usuário escolhe fonte, frequência, prazo e condição de alerta. Mostrar diff, evidência, última verificação e estado; notificar apenas mudança relevante; permitir pausar/expirar. Sem alegar background antes de haver scheduler. |
| **P2 — junto a qualquer notificação futura** | **Preferências de disponibilidade e interrupção** | Vídeo 5 | A playlist mostra chamadas e alertas proativos; o roadmap fala de rotina saudável e trata interrupções de voz, mas não especifica política de notificações proativas. | Preferências para horário silencioso, modo reunião, canal, limiar de urgência, adiamento, cooldown e limite de alertas. Chamada telefônica não deve ser padrão; ações que alterem fontes continuam exigindo aprovação explícita. |
| **P3 — validar utilidade após LLM e fontes autorizadas** | **Artefatos de trabalho com evidências** | Vídeos 1, 19, 20, 27 e 28 | O produto enfatiza evidências e o prompt pack cita relatórios, mas o roadmap não define uma experiência para criar/guardar rascunhos de documentos e painéis a partir de fontes. | Gerar relatório ou planilha em área de rascunho com referências, timestamps e limitações. Comparar com a fonte e pedir revisão humana antes de publicar ou enviar. Manter isso opcional para evitar virar dashboard genérico. |
| **Não priorizar agora** | **Entrada por Telegram/WhatsApp** | Vídeos 14, 15, 23 e 29 | A captura rápida e a PWA mobile-first já existem no plano; mensageria de terceiros não consta como conector autorizado. | Se voltar a ser considerada, exigir allowlist forte de identidade, rate limit, proteção contra replay, escopo por domínio e aviso claro de que conteúdo transita por serviço externo. A captura pela PWA local é preferível nesta fase. |

## Recursos que não recomendo trazer para o roadmap atual

- Controle irrestrito de desktop/navegador, câmera ou arquivos locais: amplia muito a superfície de ataque e não faz parte do JARVIS aprovado.
- Chamadas telefônicas proativas, atendimento de emergência ou envio automático de e-mail/eventos: envolvem disponibilidade, dados pessoais e ações externas; não cabem antes de contratos, scheduler e gates de escrita.
- VPS, túnel, endpoint público ou bot acessível pela internet: contrariam o escopo local e a política de não exposição.
- Autonomia “sem revisão” para finanças, treino/saúde ou dados empresariais: as demos são promocionais e não mudam as fronteiras MedSyn/MCID/financeiras do projeto.
- Multiplicar agentes só para parecer mais autônomo: skills isoladas, testáveis e com permissões explícitas atendem melhor aos limites já definidos.

## Encaminhamento sugerido

1. Fechar primeiro a auditoria independente do Gate 2.0-E. Este relatório não aceita o gate nem altera suas permissões.
2. Se houver interesse, registrar como propostas posteriores os itens P1: ciclo de vida do conhecimento, montagem de contexto e catálogo de skills. Fazer a especificação sem conectar serviços reais.
3. Deixar observadores e preferências de interrupção para depois de existir scheduler real e de haver autorização para as fontes correspondentes.
4. Manter voz no Gate 5 e adiar mensageria externa, controle de computador/câmera e escrita real até contratos e autorizações específicos.

## Referências do projeto

- [Contrato canônico — `AGENTS.md`](../AGENTS.md)
- [Blueprint v0.1](../JARVIS_Blueprint_v0.1.md)
- [Proposta de arquitetura Gate 2.0](GATE2_0_ARQUITETURA_PROPOSTA.md)
- [Handoff Gate 2.0-E](GATE2_0E_INTEGRACAO_WEB_API.md)
