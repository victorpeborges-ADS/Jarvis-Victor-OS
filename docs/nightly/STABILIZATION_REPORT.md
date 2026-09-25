# Relatório de estabilização pós-auditoria independente

**Data:** 2026-09-25  
**Classificação:** branch candidata para nova auditoria; não é auditoria independente nem aceite do Gate E.

## BASELINE E ISOLAMENTO

- Branch da sprint auditada: `feat/jarvis-nightly-2026-09-25-042315`.
- HEAD e commit auditado no início: `fbaca45446f31258e7a121b3a49284516fcc8243`; árvore de trabalho limpa, sem commits posteriores. A branch e o worktree auditados não foram alterados.
- Branch desta estabilização: `feat/jarvis-nightly-stabilization-2026-09-25`, em worktree independente: `/Users/vic/.codex/worktrees/jarvis-nightly-stabilization-2026-09-25/Jarvis-Victor-OS`.
- A branch candidata deriva do SHA auditado. Nenhuma alteração foi feita em `main`, no checkout original, na branch congelada, ou em outras worktrees. Não houve merge, push, deploy ou tag.
- Fixtures, testes de API, banco E2E e conteúdo de Missões usados nesta rodada são sintéticos. A API E2E cria banco SQLite temporário e o runner remove seu diretório ao terminar.

## PARECERES

| Escopo | Parecer | Evidência e limite |
|---|---|---|
| Gate E — integração web/API sintética | **BLOCKED para encerramento formal** | Os bloqueios reproduzidos receberam correções candidatas e regressões; a nova auditoria independente ainda deve revisar esta branch. Ver testes e limites abaixo. |
| Correções da Sprint Nightly | **PASS local, sintético e reproduzível** | Typecheck, lint, builds, suítes, prova de corrida do runner, recuperação de Missões e concorrência grant/revogação são executados nesta worktree. Este é o parecer do implementador. |
| Dados reais ou múltiplos processos | **BLOCKED** | A autoridade de grant continua em memória de processo único. O lock torna leitura/revogação linearizáveis somente dentro desse processo. Nenhum dado real foi acessado ou conectado. |
| Binários desktop e Android | **BLOCKED** | Builds dos frontends passaram; toolchains nativos não foram instalados e `.app`/APK não foram gerados. |

## ACHADOS, CORREÇÕES E EVIDÊNCIAS

| Achado independente reproduzido | Correção candidata | Regressão/evidência |
|---|---|---|
| TypeScript rejeitava `Node.remove()` em screenshot E2E. | Remoção de elemento condicionada a `instanceof Element`. | `apps/web/e2e/missions.spec.ts`; `npm run typecheck` e build Next. |
| Readiness aceitava qualquer HTTP 200 em `/health`, permitindo que processo alheio ganhasse a corrida depois do pré-voo. | Runner gera segredo por execução e só aceita prova HMAC de um nonce aleatório emitida pela API filha; verifica que o processo permanece vivo; não encaminha o segredo ao Playwright. A checagem inicial de porta continua sendo pré-voo, não prova de posse. | `apps/web/scripts/e2e-api-readiness.mjs`, `apps/api/main.py`; servidor falso ocupa a porta após uma verificação livre e responde 200 sem prova: regressão em `apps/web/__tests__/e2e-api-readiness.test.mjs`. O handshake verdadeiro é validado em `apps/api/test_main.py` e no E2E completo. |
| Context builder aceitava `Date.parse` NaN e timestamps no futuro; texto expirado podia entrar no contexto. | Validação de data RFC 3339, descarte de observação/verificação futuras, datas inválidas e conteúdo vencido. `now` inválido e orçamento negativo são recusados; um relógio cliente adiantado é limitado ao relógio local e não pode marcar verificação futura como válida. | `apps/web/lib/mission-validation.ts`, `context-builder.ts`, `knowledge-context.test.ts`; casos sintéticos para `invalid_timestamp`, `future_timestamp`, `future_verification`, `expired` e relógio cliente adiantado. |
| Filtros `allowed_*` do cliente podiam parecer autorização. | Nomes `client_visible_*` e contrato/documentação declaram minimização somente; rotas continuam aplicando grants no servidor antes das consultas. | `context-builder.ts`, `skill-catalog.ts`, `docs/adr/005-context-authorization-and-revocation.md`; API mantém testes de lista, domínio, ID direto e briefing sem grant adequado em `apps/api/test_local_security.py`. |
| Leituras podiam obter grants e consultar SQLite fora do lock de revogação. | `_authorized_records` mantém autorização e snapshot da consulta dentro do mesmo lock da revogação. | Probe concorrente pausa a consulta, inicia revogação e confirma que ela espera; leitura iniciada primeiro conclui sob autorização anterior, leitura subsequente recebe 403: `apps/api/test_calendar_simulator.py::test_event_read_and_revocation_linearize_on_the_same_grant_lock`. |
| Catálogo Calendar exigia sessão, mas não grant e não filtrava calendários classificados em outros domínios. | Exige grant Calendar ativo; itens classificados só são visíveis nos domínios concedidos; itens sem classificação aparecem como metadados para escolha e só podem ser classificados em domínio concedido. UI adia a busca do catálogo até obter grant. | `apps/api/calendar_sim_api.py`, `apps/web/components/integration/LocalIntegrationProvider.tsx`, `apps/api/test_calendar_simulator.py::test_calendar_catalog_requires_grant_and_hides_other_classified_domains`; E2E passa a começar sem IDs de catálogo e cria grant explícito antes da listagem. |
| `localStorage` aceitava Missões parcialmente moldadas, podendo quebrar a renderização ao usar `depends_on.length`. | Toda entrada recuperada passa pelo JSON Schema Mission v1 com formato de timestamp e validação semântica de IDs e referências. Registros inválidos/JSON corrompido são limitados e isolados em chave própria; entradas válidas permanecem. UI oferece exportar pacote de recuperação e descartar a quarentena. Se a cópia de recuperação não puder ser persistida, o original fica intacto, é oferecido para download e as mutações da tela são bloqueadas. | `mission-validation.ts`, `mission-store.ts`, `app/missoes/page.tsx`; Vitest cobre schema/referências, quota/erro da quarentena e preservação do original; E2E cobre preservar, exportar e limpar. `saveMissions` também falha fechado para objetos inválidos. |
| Capability Tauri declarava `opener:default` sem plugin instalado e em desacordo com a política declarada. | Removida a permissão; permanece `core:default`. | `apps/desktop/src-tauri/capabilities/default.json`; configuração Cargo não inclui plugin opener. Build nativo continua bloqueado por falta de Rust/Cargo. |
| Manifest listava `compare-sources` como autorizado, mas o helper não tinha call site; `knowledge-lifecycle` também era somente helper testado. | Comparação sintética foi ligada à etapa de contexto apenas depois da minimização local e seus textos/manifests deixam explícito que isso não autoriza acesso. Ciclo de vida de conhecimento segue classificado como helper, sem integração/persistência na missão. | `apps/web/lib/mission-core.ts`, `skill-catalog.ts`, E2E de Missões e Vitest. Ver classificação abaixo. |

## SEMÂNTICA DE REVOGAÇÃO EM VOO

A leitura e a revogação são linearizadas pelo lock de grants, dentro do processo. Se a leitura entra primeiro, ela mantém a concessão estável até selecionar os registros no SQLite; a revogação espera e pode terminar antes de o navegador receber os bytes. A consulta é considerada autorizada no ponto em que obteve o lock e selecionou seu snapshot. Se a revogação adquire o lock primeiro, a leitura que entrar depois falha com 403. Não existe promessa de recolher uma resposta já linearizada.

O lock não coordena workers/processos diferentes. Antes de dados reais ou múltiplos workers, a autoridade de concessões precisa passar a uma transação/coordenação compartilhada, com uma nova revisão de concorrência. A semântica sintética atual não é declaração de prontidão real.

## IMPLEMENTADO, HELPER E SCAFFOLD

| Componente | Classificação candidata | Limite comprovado |
|---|---|---|
| Missões browser local | **Integrado em fluxo sintético** | Três etapas chamam captura/classificação transitória, minimização de contexto, comparação determinística e rascunho. `captureAndClassify` produz `KnowledgeItem` transitório resumido em evidência; não grava entidade Knowledge em banco. Persistência de Mission é `localStorage`, não SQLite. |
| Comparação de fontes | **Helper integrado no contexto sintético** | Recebe apenas os candidatos incluídos pelo filtro cliente local. Não consulta API nem constitui prova de grant. |
| Ciclo de vida Knowledge | **Helper testado, não integrado à tela/persistência** | Testes unitários cobrem transições e invalidação; sem call site de produção. |
| Router/Provider e workflow simulados | **Helper/testes determinísticos** | `FakeProvider` e `FakeWorkflowAdapter` não chamam LLM, n8n, scheduler, notificação ou rede externa. Handoff é envelope manual. |
| Desktop Tauri | **Scaffold web + configuração Tauri** | TypeScript/Vite build passou; app Rust nativo não compilado. Sem permissão opener. |
| Android Capacitor | **Scaffold web + projeto Android** | Frontend e browser tests passaram; APK/Gradle não executados. |
| Hosting ADR | **Scaffold documental** | Sem adapter, PoC, benchmark, provedor selecionado ou recurso faturável. |

## TESTES DA CANDIDATA

Instalações limpas nesta worktree: `npm ci` em `apps/web`, `apps/desktop` e `apps/mobile`; `uv sync --locked --python 3.12` em `apps/api`.

| Verificação final | Resultado | Cobertura/limite |
|---|---|---|
| `rtk uv run --locked pytest` (`apps/api`) | **PASS — 149/149** | Sessão/CSRF/grants, API, catálogo Calendar, concorrência de revogação, contratos, memória e backup sintéticos. Dois avisos de depreciação Starlette/httpx e cookies do TestClient. |
| `rtk npm test` (`apps/web`) | **PASS — 63/63 em 13 arquivos** | Inclui HMAC readiness e servidor HTTP falso na corrida de porta, timestamps, comparação helper, validação/quarentena de Missões e falha de persistência. |
| `rtk npm run typecheck` (`apps/web`) | **PASS** | `tsc --noEmit`; remove o erro `Node.remove()` do cenário E2E. |
| `rtk npm run lint` (`apps/web`) | **PASS** | Sem erros/avisos ESLint; o script `next lint` tem aviso de depreciação para Next 16. |
| `rtk npm run build` (`apps/web`) | **PASS** | Build Next 15.5.26, páginas estáticas e verificação de tipos. |
| `rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' JARVIS_E2E_SCREENSHOT_DIR='/tmp/jarvis-nightly-stabilization-captures' npm run e2e` | **PASS — 36/36** | 18 cenários em Chromium desktop e os mesmos 18 em mobile. Inclui sessão/CSRF, isolamento DEMO/API, catálogo sob grant, sync/proveniência/revogação, recuperação de Missões e falha de quota com origem preservada. Runner constrói, inicia sua API e Next e usa SQLite temporário sintético. |
| `rtk npm test`, `rtk npm run lint`, `rtk npm run build`, `rtk npm run e2e` (`apps/mobile`) | **PASS — 2 unitários + 4 E2E** | Oxlint e TypeScript/Vite passaram; E2E browser desktop/mobile da shell Capacitor, sem APK. |
| `rtk npm run build` (`apps/desktop`) | **PASS** | TypeScript/Vite passou; sem compilação nativa Tauri. |
| Verificação nativa Tauri/Android | **BLOCKED / não executada** | Nenhum binário nativo gerado; toolchains nativos não instalados. |
| `rtk git diff --check` | **PASS** | Sem erros de whitespace antes dos commits. |

O primeiro `npm test` desta estabilização expôs contagem duplicada de quarentena e um teste que assumia o formato anterior do pacote; ambos foram corrigidos. A revisão também acrescentou testes para quota ao salvar a quarentena e ao limpar a chave original. O E2E integrado inicialmente expôs uma corrida real da UI: publicar o grant atualizava eventos e abortava a busca do catálogo; o provider foi ajustado para completar o carregamento autorizado antes da atualização visível. As falhas intermediárias não foram descartadas como falsos positivos. Não há falha conhecida remanescente nas suítes finais; o limite é que são testes locais sintéticos, sem processo múltiplo ou conector real.

## LIMITES E PRÓXIMAS AÇÕES

- Nenhuma modificação no schema SQLite ou implementação de memória foi feita nesta estabilização; a prova browser/API usa somente o banco sintético temporário já existente.
- Sessões e grants continuam voláteis, em processo único. Missões seguem em `localStorage` e não sincronizam entre abas/dispositivos.
- Não foram executados OAuth, contas reais, Calendar real, Gmail, Drive, LLM, serviço pago, listener público, túnel, deploy remoto ou ação externa.
- Gate E só pode ser encerrado depois de uma auditoria independente da branch/commit final e aceite explícito separado.
- Antes de uso real: coordenação compartilhada de grants, threat review do catálogo/conector, decisão de retenção/proveniência/expurgo e política de recuperação/backup, além dos gates próprios para OAuth e contas. Toolchains nativos exigem provisionamento aprovado e validação de permissões.

## RETOMADA

Worktree: `/Users/vic/.codex/worktrees/jarvis-nightly-stabilization-2026-09-25/Jarvis-Victor-OS`. Leia a branch e seu HEAD com `rtk git status --short`, `rtk git branch --show-current`, `rtk git rev-parse HEAD`. Commits da estabilização e HEAD final serão registrados no handoff da execução. Execute as suítes sem invocar Playwright diretamente; use o runner oficial com origem IPv6 loopback e diretório de screenshot sob `/tmp`. Entregue esta branch a outro auditor como read-only; não faça merge, push ou deploy.
