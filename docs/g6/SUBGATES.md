# Subgates G6

Todos os gates herdam as restrições do ADR-010 e dos princípios em AGENTS.md. PASS requer evidência registrada em commit e nenhuma falha aberta de segurança/UX; uma suíte parcial não autoriza gate. FAIL ocorre quando um critério binário não é demonstrado. BLOCKED registra dependência externa ou técnica ausente sem converter intenção em aprovação.

## G6.0 — Architecture & Contracts

**Objetivo:** documentar arquitetura auditada de Web/API/macOS/Android, contratos de cliente, runtime, voz, identidade/continuidade, ameaças, backlog e critérios.

**Entrada:** main documental 82b3c244c796b68b181dbf127509caababd2258e; aceite G5 ab7f856ee834b7f9923d914639e0e345dbf57322; código atual auditado.

**Entregáveis:** onze documentos docs/g6/, sete diagramas Mermaid, matriz de arquitetura atual e alvo, decisões abertas e sequência.

**Verificação:** links relativos; caminhos e nomes de código conferidos; presença e parsing dos diagramas se validador já instalado; git diff --check; git fsck; HEAD pai correto; worktree limpa após commit.

**Segurança:** nenhum código/configuração/permissão/runtime alterado; nenhuma chamada externa, conta ou dado real.

**UX:** terminologia comum em PT-BR, estados DEMO/local/offline visíveis, áreas de produto mapeadas por cliente.

**PASS:** os onze documentos existem; os sete diagramas são sintaticamente válidos ou a limitação de tooling está documentada; as verificações Git passam; revisão não encontra afirmação de feature ativa inexistente.

**FAIL:** documento faltante, origem de código presumida sem verificação, diagrama inválido sem nota, mudança funcional, branch fora do baseline, G5 reaberto ou qualquer integração habilitada.

**Fora do escopo:** cliente/API, SDK, build nativo, microfone/STT/TTS, serviço/SDK, deploy/push/tag.

## G6.1 — macOS Connected Client

**Objetivo:** cliente macOS conectado ao Victor OS local por uma API sidecar iniciada e supervisionada pelo .app.

**Entrada:** contrato OpenAPI versionado/gerado; G6-MAC-001 packaging/runtime; decisão de origem/porta; threat model e plano de migração.

**Entregáveis:** Runtime Manager; sidecar de API empacotado; readiness/health distinto de DEMO; estados sessão/grants/dataset; navegação integrada; atualização e backup; logs redigidos.

**Testes:** lifecycle abrir/fechar/crash; duas inicializações; processo falso/porta em uso; readiness atrasada e DB indisponível; API bind/probe LAN; CORS preflight/Origin/CSP/cookie/CSRF no bundle; reautenticação pós-restart; migração em cópia sintética; jornada de missão/revisão.

**Segurança:** somente child próprio; bind loopback; nenhum comando shell arbitrário; nenhuma permissão Tauri ampla; CORS estrito; processos e sessões não persistidos; side effects sempre API-authorized.

**UX:** Starting, Ready, Degraded, Offline, Session expired, Grant missing e Database unavailable com motivo e retry controlado; nunca DEMO como fallback; jornada e proveniência iguais à Web.

**PASS:** build empacotado demonstrado no macOS suportado, todos os testes acima sem abrir rede, DB preservado, restart invalida sessão e grants, revisão humana passa pelo endpoint existente.

**FAIL:** processo alheio aceito, bind de rede, wildcard de origin, usuário conclui que a missão foi salva quando só está local, session/grant restaurado sem autenticação ou sidecar órfão.

**Fora do escopo:** API pública, OAuth/conta, dados pessoais, provider real, cloud, LAN, multiworker ou mudança do modelo G5.

## G6.2 — Voice Foundation

**Objetivo:** habilitar interface de voz em primeiro plano que usa mesma conversa e backend, com push-to-talk e UX previsível.

**Entrada:** G6.1 aceito; decisão explícita de provider, locale, retenção, orçamento e permissão por plataforma.

**Entregáveis:** state machine, abstrações STT/TTS, indicador e controle de microfone, transcript parcial/final, barge-in/cancel, integração com conversas e approval UI.

**Testes:** matriz de cada transição; sem fala, timeout, permissão negada, troca/desconexão de dispositivo, erro STT/TTS, API offline, sessão/grant expirado, barge-in com/sem request enviada, transcript mal compreendido e tentativa de dizer “sim”.

**Segurança:** PTT foreground por default; transcript final revisado; nenhum áudio bruto em storage/log; nenhum side effect por transcript parcial; nenhuma decisão sensível somente acústica; API revalida tudo.

**UX:** estado sempre visível, português e saída interrompível; erros não iniciam provider alternativo/remoto silenciosamente; TTS sensível é privado.

**PASS:** testes de estado e permissão passam em dispositivos/plataformas definidos; telemetria não tem audio/transcript; decisão em tela e backend rejeita falta de grants.

**FAIL:** wake word oculto, gravação em background, replay aprova, falsa confirmação acústica, ou command duplicado ao cancelar voz.

**Fora do escopo:** clone de voz, fala de pessoa sem licença/autorização, wake word, API paga sem gate, provider real não aprovado, processamento de dados pessoais.

## G6.3 — Android Client Foundation

**Objetivo:** evoluir shell Capacitor para cliente Android com UX/state/contracts coerentes, sem apresentar acesso remoto inexistente.

**Entrada:** G6.1 contrato OpenAPI congelado; design system e navegação mapeados; requisitos de plataforma aprovados.

**Entregáveis:** telas semânticas compartilhadas, estado local explícito, acessibilidade/mobile, sessão não conectada visível, diagnóstico sem segredo, build debug somente se toolchain aprovada.

**Testes:** build/typecheck/lint/testes UI; viewport/emulador; navegação e leitor de tela; reinstalação e limpeza de rascunho; tentativas de acesso Mac localhost; fallback DEMO negativo.

**Segurança:** sem API LAN/remota, OAuth, background worker, tokens em localStorage, push, fontes locais sem escolha explícita ou sync silencioso.

**UX:** “neste aparelho” para dados locais; Missões/Approvals conectadas desabilitadas com explicação; demais áreas mantêm semântica comum.

**PASS:** cliente funciona como shell local, limitações visíveis, nenhum endpoint remoto é tentado e aprovação não é simulada.

**FAIL:** UI diz sincronizado/compartilhado, aponta ao loopback do Mac, cria decisões fictícias ou persiste segredo de sessão.

**Fora do escopo:** continuidade Android↔Mac, release APK, contas reais, rede remota e push.

## G6.4 — Identity & Continuity

**Objetivo:** projetar e aprovar modelo real de identidade, device provisioning, auth, sessões/grants e continuidade antes de conectar aparelhos.

**Entrada:** threat model remoto; opções A–E; requisitos de privacidade, retenção, custos, operação e recuperação.

**Entregáveis:** ADR(s) para decisões de fato tomadas; schema/protocolo; rota de enrollment, revogação, recuperação; conflitos/offline; model de dados e migração; política de chaves e secure storage.

**Testes:** abuse cases, replay, roubo/revogação de aparelho, recovery, conflito de revisão/artefato, race/idempotência, perda de conectividade, backup e rotação.

**Segurança:** autenticação remota comprovável; grants revogáveis por aparelho; transporte autenticado; princípio de mínimo dado; key lifecycle completo; autoridade de approval inequívoca.

**UX:** estado de sessão/dispositivo e dado sincronizado visíveis; offline/stale sem mutação silenciosa; consentimento granular antes de upload.

**PASS:** arquitetura e novo boundary aceitos explicitamente antes de código de sync; ensaios de revogação e stale aprovados no synthetic test bed.

**FAIL:** device_id tratado como credencial, sessão/grant copiado, banco sincronizado inteiro por conveniência, approval stale ou recuperação que contorna identidade.

**Fora do escopo enquanto não aceito:** implementação de cloud/sync/remoto, conta real ou exposição pública.

## G6.5 — Product Integration QA

**Objetivo:** testar o produto conjunto e demonstrar paridade sem confundir estados ou fontes.

**Entrada:** G6.1–G6.3 implementados; G6.4 apenas se houver continuidade incluída, com aceite próprio.

**Entregáveis:** matriz de workflows por cliente, accessibility review, relatório de origem/recência e conteúdo, capturas comparativas, release criteria e regressões.

**Testes:** APIs completas, Vitest, typecheck, lint, build, E2E em cada cliente e estado offline/degraded; cenários de sessão/grant/revogação/revisão; sizing e acessibilidade.

**Segurança:** nenhuma rota ou feature client-side bypass; origins/permissões mínimos; logs revisados; boundary no release declarado por escrito.

**UX:** Mesmo JARVIS em Agora, Conversa, Inbox, Domínios, Aprovações, Fontes, Missões e Integração; nomes, estados, foco, leitura, contrastes e layout mobile consistentes.

**PASS:** zero blocker de segurança/acessibilidade/proveniência; todas as plataformas e limitações do release declaradas com evidência reproduzível.

**FAIL:** um cliente exibe aprovação desatualizada como atual, DEMO como dado local real, continuidade não provisionada ou regra de autorização própria.

**Fora do escopo:** merge/push/tag/deploy sem autorização independente.
