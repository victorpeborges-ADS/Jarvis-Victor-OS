# JARVIS — Victor OS + Victor Context Hub
**Blueprint de produto e engenharia · v0.1 · 23/09/2026**

## Visão
Um único produto pessoal: JARVIS é a interface conversacional/visual/voz; Victor OS é o motor de planejamento e decisões; Victor Context Hub é a camada de memória, proveniência e interoperabilidade. O produto deve reduzir a quantidade de aplicativos que Victor precisa abrir e evitar repetição de informações, sem tomar decisões externas não aprovadas.

## Princípios não negociáveis
1. **Fonte de verdade por domínio:** Calendar=compromissos; Gmail=comunicações; Drive=documentação; GitHub/código=estado de implementação; ferramentas de projeto=estado de tarefas; Aprender AI=estudo; SOFF=finanças. Os dados internos do JARVIS indexam referências, não alegam substituir a fonte.
2. **Proveniência/recência:** cada fato exibe origem, ID/URL quando permitido, timestamp, última verificação, validade, confiança e escopo de acesso. Distinguir observação, inferência, proposta e decisão aprovada.
3. **Humano no comando:** consultar automaticamente dentro das permissões; criar rascunhos e propor alterações; pedir confirmação explícita para enviar e-mail, alterar agenda, transferir dados, publicar, fazer deploy ou realizar ações financeiras.
4. **Separação de domínios:** pessoal, empresarial/comercial, MedSyn e MCID precisam de escopos e políticas distintas. Nunca copiar documentos institucionais restritos nem dados sensíveis de saúde para banco pessoal sem autorização adequada. Preferir referência e metadados autorizados.
5. **Sem falsa autonomia:** não simular integração real quando só existe mock; estados `mock`, `connected`, `stale`, `error`, `pending_approval` devem ser visíveis. Sem prometer trabalho em background sem scheduler real.
6. **Uma única arquitetura e backlog:** monorepo ou repositório existente viável, `AGENTS.md` canônico e regras auxiliares específicas. Não criar três produtos ou duplicar SOFF/Aprender AI.
7. **Mobile-first e acessível:** interface PT-BR, estética sóbria e pessoal, teclado/screen reader, WCAG 2.2 AA como meta, modo claro/escuro, redução de movimento, estados de rede e carregamento claros. Preferir desempenho e clareza a animações supérfluas.
8. **Manter rotina real:** automação não pode incentivar sobrecarga. Proteger sono, saúde, casamento, compromissos e jornada; manter atividades profissionais distintas quando exigido.

## A experiência norteadora (North Star)
Victor abre o JARVIS e, em até 5 segundos de leitura, entende o dia: compromisso seguinte, uma prioridade essencial, um alerta com consequência real e sua energia/capacidade opcionalmente informadas. Pode digitar ou falar: “O que mudou? Tenho 45 minutos; o que adianto?” O JARVIS apresenta uma proposta com justificativa, fontes e um CTA inequívoco. Ao aprovar, executa apenas a ação autorizada e registra evidência; ao rejeitar, respeita a decisão.

### Shell de produto
- **Agora:** tela inicial orientada ao momento. Próximo compromisso, timeline compacta, apenas 1–3 decisões úteis, briefing resumido.
- **Perguntar ao JARVIS:** campo universal de texto e botão de voz; sugestões contextuais; respostas com evidências e ações confirmáveis; streaming e cancelamento.
- **Caixa de entrada:** captar texto/voz/link/arquivo e classificar como tarefa, evento, referência, projeto, pessoa ou nota; revisão humana antes de gravar ações externas.
- **Domínios:** Trabalho/CGMUR, MedSyn, CRIVO, Carreira, Aprender AI, Saúde, Finanças, Família/Fé. Domínios são filtros da mesma memória, não aplicativos completos concorrentes.
- **Memória/Origens:** origem de cada conclusão, data de atualização, eventos correlatos, decisões e contradições.
- **Central de aprovação:** fila explícita de mudanças, diffs em linguagem natural, escopo da autorização, revogação quando possível, log auditável.
- **Configurações e privacidade:** conectores, escopos, armazenamento, exportação, retenção, credenciais e exclusão.

### Design language
Estética premium discreta: tipografia legível, hierarquia editorial, superfícies claras/escura cuidadosamente calibradas, uma cor de ação principal, espaço em branco, animações funcionais. Visualização de informações só onde aumenta a capacidade de decisão. Nunca criar um cockpit com oito painéis exibidos por padrão. Layout desktop com coluna central 'Agora', barra de comando global e painel lateral de contexto que aparece sob demanda; mobile com navegação inferior simples e comando universal sempre acessível. Voz tem paridade com texto e nunca é obrigatória.

## Arquitetura-alvo evolutiva (a confirmar após auditoria local)
- Frontend: Next.js + React + TypeScript; Tailwind e componentes acessíveis customizados a partir do design system; PWA responsiva; animação frugal. Validar compatibilidade com repositórios locais antes de escolher versões.
- Backend: FastAPI Python; esquema de OpenAPI tipado; serviços explícitos para ingestão, entidade, evento, agenda, propostas, approvals, conectores, jobs e audit log.
- Armazenamento inicial: SQLite para PoC local se viável; migrar para PostgreSQL quando múltiplos conectores concorrentes, sessões ou volumetria justificarem; considerar pgvector apenas após testar busca convencional. Backups/restore testados.
- Fluxos: n8n para rotinas e automações limitadas. Backend mantém políticas, aprovação, idempotência, autenticação e persistência; o n8n não vira a fonte de verdade.
- Modelos IA: camada de provedores substituível (OpenAI, Gemini, modelos locais quando disponíveis), roteamento explícito por custo, privacidade e capacidade; não acoplar esquema de memória ao fornecedor.
- Integrações MVP: Google Calendar e Gmail em modo somente leitura com OAuth de menor privilégio, após aprovação do escopo. Drive documental em segunda onda. Demais conectores entram por adapters conforme autorização e disponibilidade.
- Infraestrutura inicial: Mac mini como ambiente pessoal de desenvolvimento/execução, sem exposição pública de portas nem tunelamento desprotegido. HTTPS, autenticação forte, secrets locais protegidos, mínimo logging de dados privados.

## Entidades nucleares
- `Source`: provider, account, scope, sync_status, last_success, consent.
- `Event`: external_ref, source_id, event_type, occurred_at, observed_at, payload_minimized, sensitivity, TTL.
- `Entity`: pessoa/projeto/tarefa/compromisso/meta/documento; owner/domain e aliases.
- `Relation`: from_entity, to_entity, relation_type, evidence_event_ids, review_status.
- `Decision`: proposal, rationale, conflicts, alternatives, state, approved_by, approved_at.
- `Action`: decision_id, action_kind, target_connector, minimal_payload, idempotency_key, execution_state, external_result.
- `Preference`: explicit_only, scope, version, changed_at; preferências nunca sobrepõem fatos atuais.
- `AuditEntry`: who, when, what, why, object, approval_ref e resultado; redigir segredos.

## Ordem das entregas com gates
**Gate 0 — Auditoria e plano aprovado:** inspecionar repositórios e stack local, identificar o que é reaproveitável sem tocar em sistemas institucionais, mapear variáveis e credenciais só por nomes, produzir riscos, estrutura proposta e backlog. Nenhuma ação destrutiva.

**Gate 1 — Protótipo interativo completo em mocks:** telas Agora, JARVIS, Inbox, Domínios e Aprovações; 3 jornadas ponta-a-ponta com fixtures coerentes; design system e navegação responsiva; estado vazio/erro/stale/loading; nenhuma integração fingida.

**Gate 2 — Vertical slice real read-only:** API FastAPI, armazenamento local, OAuth Calendar e Gmail com escopos mínimos, sincronização incremental ou polling prudente, eventos com proveniência, briefing determinístico + camada LLM opcional, testes de falhas. Sem gravação nos provedores.

**Gate 3 — Propostas supervisionadas:** ações sugeridas com revisão e confirmação; inicialmente criação de rascunho local e simulação de atualização de agenda; só habilitar escrita real após testes de idempotência, concorrência, revogação e consentimento.

**Gate 4 — Expansão contextual:** Drive, GitHub e projetos pessoais, com fronteira MCID/MedSyn; Aprender AI e SOFF via adapters autorizados. Implementar busca e memória semântica apenas quando um conjunto de testes provar benefício.

**Gate 5 — Voz/PWA refinadas:** transcrição, TTS, permissão de microfone, tratamento de interrupções, feedback visual e fallback completo por texto; acesso remoto somente após revisão de threat model.

## Jornadas obrigatórias de teste
1. **Bom dia:** ler o calendário e últimas comunicações relevantes, obter prioridades explícitas, gerar briefing com evidência de cada item; nunca confundir um e-mail promocional com obrigação real.
2. **Imprevisto:** novo compromisso conflita com academia e entrega da MedSyn; sugerir 2 alternativas respeitando compromissos e distinguir sugestão de alteração realizada.
3. **Captura:** usuário dita ideia de CRIVO; classificar e vincular ao projeto sem criar automaticamente reunião, mandar e-mail nem afetar o backlog institucional.
4. **Desatualização:** fonte não sincroniza há 24h; a interface mostra informação possivelmente obsoleta, não apresenta silêncio como confirmação.
5. **Privacidade:** um pedido sobre assunto pessoal não recupera documentos institucionais protegidos; log sem dados sensíveis.

## Métricas internas (metas para testar, não desempenho alcançado)
- Em 5 segundos, identificar próximo compromisso, prioridade e alerta na página Agora.
- Em 2 interações, capturar uma nota ou consultar a agenda pelo celular.
- 100% das alterações externas devem apresentar escopo, alvo, consequência e aprovação antes da execução.
- 100% de fatos críticos no briefing devem ter evidência verificável ou serem explicitamente classificados como inferência.
- Zero regressão conhecida em isolamento de domínios, vazamento de segredos e duplicação de ações em testes.
- WCAG 2.2 AA como critério de revisão; fluxos principais totalmente utilizáveis por teclado.
- Lighthouse/Playwright/perfil de performance com orçamento definido com base no hardware real, não números inventados.

## Governança de agentes
`AGENTS.md` no repositório é o contrato comum: princípios, arquitetura decidida, scripts, políticas de acesso, convenções de teste, checklist e áreas proibidas. OpenCode implementa fatias isoladas em branches próprias. Codex audita arquitetura/segurança e corrige falhas de maior risco em alterações delimitadas. Cursor implementa e refina UX/integração visual com Playwright e testes manuais. Para evitar conflitos, não alterar os mesmos arquivos simultaneamente em worktrees diferentes; cada fase gera commit e handoff com estado real, testes, riscos e diffs.

## O que deliberadamente NÃO entra no primeiro ciclo
Wake word permanente, Android Auto, automação financeira, uso de dados clínicos, acesso irrestrito a arquivos do MCID, exposição pública do Mac, múltiplos agentes autônomos escrevendo nas mesmas fontes, customização estética infinita, dashboards extensos e migração indiscriminada do histórico inteiro para banco local.
