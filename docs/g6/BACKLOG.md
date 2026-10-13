# Backlog implementável G6

Prioridades indicam precedência, não estimativa de duração. “Arquivos prováveis” podem mudar após spike; qualquer mudança deve preservar contratos e boundaries descritos nos documentos do diretório.

## P0 — fundação

### G6-MAC-001 — Runtime Manager e child de prova

- **Subgate:** G6.1
- **Status:** a reauditoria de MAC-001.1 validou a linearização, mas encontrou retorno de B em `stop(A)` e flakiness pré-ready. A candidata MAC-001.2 corrige esses dois pontos, com evidências em [`g6-1/G6_MAC_001_2_REPORT.md`](g6-1/G6_MAC_001_2_REPORT.md), pendente de reauditoria independente e decisão do proprietário.
- **Objetivo executado:** iniciar, validar readiness por ID da instância, observar e finalizar um helper child iniciado pelo app.
- **Arquivos alterados:** `apps/desktop/src-tauri/src/{lib.rs,main.rs,runtime_manager.rs}`, `apps/desktop/src/App.tsx`, `apps/desktop/src/App.css`, `apps/desktop/README.md` e documentação `docs/g6/g6-1/`.
- **Testes:** ciclo completo, startup timeout, readiness errada/antiga, crash antes/depois de readiness, chamadas concorrentes, restart explícito, shutdown timeout, processo independente preservado e spawn/reap do executável Tauri release.
- **Limite do status:** não integra a API Python, SQLite, endpoint, sessão, grant ou dados de produto; não gera `.app` nem aceita os itens restantes de G6.1.
- **Próxima dependência:** MAC-002 permanece não iniciado. Só deve ser considerado depois da decisão de aceite de MAC-001.2; este subgate não autoriza conexão.

### G6-MAC-002 — Endpoint, porta e origin do WebView

- **Subgate:** G6.1
- **Objetivo:** escolher e testar transporte loopback/IPC estreito para o endpoint possuído pelo runtime.
- **Arquivos prováveis:** apps/api/serve.py, server_config.py, loopback.py, main.py, apps/desktop/src-tauri/tauri.conf.json, capabilities/default.json, cliente local.
- **Dependências:** G6-MAC-001; DEC-03/04/05.
- **Risco:** processo externo, port race, cookie ou CORS aceito por origem falsa.
- **Testes:** porta dinâmica concorrente, endpoint falso, CORS preflight, Origin recusada, CSP, Host, CSRF, cookie/SameSite em app empacotado.
- **Pronto quando:** endpoint pertence ao child comprovado; listener loopback; readiness DB autenticada por desafio; origin exata; G5 API/E2E permanecem verdes.

### G6-MAC-003 — Sidecar da API oficial

- **Subgate:** G6.1
- **Objetivo:** incluir FastAPI pelo runner oficial num bundle macOS reproduzível.
- **Arquivos prováveis:** apps/api/serve.py, pyproject.toml, uv.lock, artefatos de build; apps/desktop/src-tauri/tauri.conf.json e script local de bundle.
- **Dependências:** G6-MAC-001/002; DEC-01/05; versões de target suportadas.
- **Risco:** tamanho, libs dinâmicas, migração no primeiro boot e assinatura.
- **Testes:** startup no bundle limpo; banco sintético; /ready; falha do SQLite; shutdown; arm64 e target adicional declarado; assinatura do artefato.
- **Pronto quando:** não há chamada Uvicorn import-string que contorne serve.py; no app, API só escuta loopback; fixture DEMO continua separada.

### G6-API-001 — OpenAPI congelado e typesafe client

- **Subgate:** G6.1
- **Objetivo:** fornecer contrato TS reproduzível da API sem espelhar política.
- **Arquivos prováveis:** apps/api/main.py, novos artefatos apps/api/openapi.json ou schema gerado, apps/web/lib/local-api.ts, diretório client compartilhado apenas se aprovado.
- **Dependências:** G6-MAC-002; DEC-06/07.
- **Risco:** drift de schema ou acoplamento do client a lógica de grants.
- **Testes:** geração idempotente, diff de schema, tipos nos dois clientes, erros 401/403/409/422.
- **Pronto quando:** CI detecta drift; apenas Pydantic/OpenAPI define shapes; API server decide toda autorização.

### G6-MAC-004 — Jornada canônica e estado no macOS

- **Subgate:** G6.1
- **Objetivo:** ligar Agora/Inbox/Missões/Aprovações/Integração às rotas sintéticas com estados explícitos.
- **Arquivos prováveis:** apps/desktop/src/App.tsx, App.css, cliente gerado e API de integração.
- **Dependências:** G6-MAC-003; G6-API-001.
- **Risco:** capturas locais aparentarem persistência de missão.
- **Testes:** sessão, logout/restart, grant ausente/revogado, criar/ler missão, decisão revision-bound, backend offline, dataset.
- **Pronto quando:** produto informa origem e persistência de cada item; approval e provenance vêm da API; sem estado conectado armazenado como autoridade local.

### G6-MAC-005 — DB e observabilidade de release

- **Subgate:** G6.1
- **Objetivo:** preservar banco e diagnósticos em atualização/crash.
- **Arquivos prováveis:** apps/api/memory_store.py, scripts de migração/backup, Runtime Manager, guia de distribuição.
- **Dependências:** sidecar integrado; DEC-08.
- **Risco:** migração truncada, backup sensível ou log com conteúdo.
- **Testes:** backup sintético, upgrade N→N+1, falha no meio, recovery em cópia, inspeção de logs.
- **Pronto quando:** plano de backup/recovery é reproduzível e dados originais não são sobrescritos; logs obedecem allowlist.

### G6-CON-001 — Estados comuns e dataset

- **Subgate:** G6.1 + G6.3
- **Objetivo:** projetar cada superfície para Connectivity, Session, Grant, Mission, Approval e Dataset.
- **Arquivos prováveis:** apps/web/components/..., apps/desktop/src/App.tsx, apps/mobile/src/App.tsx, docs e tipos gerados.
- **Dependências:** OpenAPI e contrato comum.
- **Risco:** cliente confundir DEMO, dado sintético API e conteúdo local.
- **Testes:** tabela de transições; screenshot/foco/leitor; ausência de fallback com rede desligada.
- **Pronto quando:** cada rótulo se liga a origem real e nenhum cliente promove estado stale.

### G6-VOICE-001 — PTT state machine, sem provider real

- **Subgate:** G6.2
- **Objetivo:** construir controles e estados de voz com fakes, sem captura real de áudio.
- **Arquivos prováveis:** novo módulo de voz do cliente Mac, UI de Conversa, tipos e testes unitários; sem mic entitlement/provider.
- **Dependências:** G6.1 aceito; threat model.
- **Risco:** fake parecer voz conectada e teste omitir permissão/SO.
- **Testes:** todas as transições, barge-in, cancel, timeout, erro, pending approval, transcript placeholder marcado sintético.
- **Pronto quando:** UX de estado pode ser revisada sem acesso ao microfone e nenhuma ação de produto é tomada pelo mock.

### G6-ID-001 — Discovery/ADR de continuidade

- **Subgate:** preparação para G6.4
- **Objetivo:** comparar opções A–E e especificar atores, dados, recovery, custos e conflitos.
- **Arquivos prováveis:** docs/g6/DECISIONS_PENDING.md, ADR novo somente depois da escolha, threat model.
- **Dependências:** requisitos de produto e aceite de novo boundary.
- **Risco:** projetar cloud por conveniência sem atribuir operação e retenção.
- **Testes:** revisão de abuse cases e critérios de revogação/replay/conflict.
- **Pronto quando:** escolha explicitamente aceita ou G6.4 permanece BLOCKED; nenhuma conexão remota ativada antes.

## P1 — produto

### G6-VOICE-002 — STT local selecionado

- **Subgate:** G6.2
- **Objetivo:** conectar provider de sistema/aprovado para PTT, parcial e final.
- **Arquivos prováveis:** adapter VoiceProvider por plataforma, capabilities, permissions e fluxo Conversa.
- **Dependências:** DEC-09; consentimento de dados/custo; licença/locale.
- **Risco:** API dependente de rede, gravação prolongada ou transcript enviada antes da revisão.
- **Testes:** permissão, suporte pt-BR/offline, silêncio, timeout, endpoint indisponível, transcript parcial não comanda.
- **Pronto quando:** provider e dados são rotulados; captura termina; transcript final é visível/editável; dados não são persistidos automaticamente.

### G6-VOICE-003 — TTS e interrupção

- **Subgate:** G6.2
- **Objetivo:** falar respostas não sensíveis, com cancelar/barge-in e provider substituível.
- **Arquivos prováveis:** adapter TTS, controles e política de privacidade da saída.
- **Dependências:** DEC-09 e G6-VOICE-002.
- **Risco:** leitura de conteúdo para alto-falante/lockscreen.
- **Testes:** stop imediato, troca de rota de áudio, interrupção do SO, conteúdo restrito, voice licensing.
- **Pronto quando:** qualquer output interrompe; conteúdo privado não é narrado sem política; provider tem custo/licença revisados.

### G6-VOICE-004 — Pedido de ação por voz e approval UI

- **Subgate:** G6.2
- **Objetivo:** criar intenção pelo PTT e ligar a revisão canônica sem aprovação acústica.
- **Arquivos prováveis:** Conversa, API client, approval route/view e state machine.
- **Dependências:** G6-VOICE-001/002; G6-MAC-004.
- **Risco:** falso “sim”, replay, request duplicado na interrupção.
- **Testes:** transcript revisado, falta de grant, revisão antiga, expected hash errado, idempotência, pending approval.
- **Pronto quando:** decisão exige tela explícita e servidor revalida sessão/grant/revisão/hash.

### G6-AND-001 — Android UX/client foundation

- **Subgate:** G6.3
- **Objetivo:** mapear áreas canônicas no shell Android, state model local e acessibilidade.
- **Arquivos prováveis:** apps/mobile/src/App.tsx, CSS, tipos API; não criar endpoint remoto.
- **Dependências:** G6-API-001; policy de capacidades.
- **Risco:** UI sugerir continuidade.
- **Testes:** build web de shell, testes UI, viewport Android, teclado/leitor, network disabled e endpoint negativo.
- **Pronto quando:** rascunhos indicam “neste aparelho”; missões e approval conectadas são indisponíveis explicitamente; nenhum sync automático.

### G6-AND-002 — Empacotamento Android debug

- **Subgate:** G6.3
- **Objetivo:** criar artefato debug para avaliação local após SDK provisionado com autorização.
- **Arquivos prováveis:** apps/mobile/android/, capacitor.config.ts, guia local.
- **Dependências:** SDK/Android Studio disponíveis; signing debug; review de permissions.
- **Risco:** plugin/manifesto adiciona capability inesperada.
- **Testes:** build/install em emulador, manifest permissions, rede ausente, dados locais de teste, uninstall.
- **Pronto quando:** debug build reproduzível sem conta/endpoint e nenhum dado real; NÃO significa release ou conectividade.

### G6-ID-002 — Design de chaves e enrollment

- **Subgate:** G6.4
- **Objetivo:** especificar API de device key abstraction, challenge, enrollment, revogação, recuperação.
- **Arquivos prováveis:** novos ADR/protocol/types, futuro Keychain/Keystore adapter.
- **Dependências:** G6-ID-001; decisão de identidade/transporte; security review.
- **Risco:** chave local confundida com autorização ou recovery bypass.
- **Testes:** ameaça de device clone, replay, chave perdida, logout, revocation offline e rotação.
- **Pronto quando:** servidor autentica cada dispositivo, grant é independente, revoke e recuperação são testáveis.

### G6-ID-003 — Protocolo de continuidade e conflitos

- **Subgate:** G6.4
- **Objetivo:** definir quais entidades sincronizam e regras para mission/artifact/review revisions.
- **Arquivos prováveis:** schema/migration future, API contract, sync engine futuro, UI stale/conflict.
- **Dependências:** G6-ID-002; decisão A–E; retention/privacy review.
- **Risco:** aprovação conflita com versão de artefato ou exclusão offline.
- **Testes:** stale approval, duplicate delivery, reordered delta, tombstone, retry/idempotency, domain isolation.
- **Pronto quando:** autoridade de missão/approval e resolução de cada conflito são inequívocas; só então habilitar transporte no gate seguinte.

## P2 — polish

### G6-LOCAL-001 — Automações locais persistentes

- **Subgate:** macOS local, primeiro marco
- **Estado:** implementação candidata descrita em [LOCAL_AUTOMATIONS.md](LOCAL_AUTOMATIONS.md); sem aceite até revisão e smoke manual da janela.
- **Objetivo:** lembretes, briefing e revisão local agendados apenas enquanto o runtime do app está ativo.
- **Dependências:** SQLite local, supervisor MAC-003, sessão G5 e grant mission:read revalidado para leitura.
- **Limites:** sem daemon, notificação de sistema, rede/modelo ou ação externa; execuções perdidas exigem recuperação explícita.
- **Testes:** relógio injetável, DST/fuso, quiet hours, atraso/reboot, idempotência concorrente, retries limitados, migração, API supervisionada, IPC e build.
- **Aceite pendente:** testes focados verdes e smoke Tauri real confirmando cadastro, aviso/rascunho, pausa/retomada, missed-run e recuperação consentida.

### G6-UX-001 — Paridade visual/editorial

- **Subgate:** G6.5
- **Objetivo:** alinhar navegação, PT-BR, nomenclatura, origem e acessibilidade nos três clientes.
- **Arquivos prováveis:** telas e tokens em Web, Desktop e Mobile.
- **Dependências:** estados e contratos estáveis.
- **Risco:** divergência sutil entre locale/plat.
- **Testes:** inspeção visual nos breakpoints, teclado, leitor, contraste/reduced motion, pluralização e texto longo.
- **Pronto quando:** matriz de screenshot revisada, sem label divergente ou overflow bloqueador.

### G6-OBS-001 — Diagnóstico local

- **Subgate:** G6.5
- **Objetivo:** expor estado técnico necessário sem mostrar tokens ou conteúdo.
- **Arquivos prováveis:** view Integração, collector local, docs de suporte.
- **Dependências:** formato comum de error/correlation.
- **Risco:** log PII e correlation ID persistente.
- **Testes:** snapshots redacted, export local mínimo, limpeza/rotação.
- **Pronto quando:** logs allowlist revisados e correlation expira conforme política.

### G6-COST-001 — Revisão de custo futuro

- **Subgate:** G6.5 ou antes de provider remoto
- **Objetivo:** registrar custos e dados enviados de voz, backend, sync e push por cenário.
- **Arquivos prováveis:** docs e ADRs de provider/architecture.
- **Dependências:** shortlist de provider e arquitetura do G6.4.
- **Risco:** protótipo “grátis” virar promessa de produção.
- **Testes:** revisão de preço atualizado, tráfego/retention e hipótese de volume.
- **Pronto quando:** custos recorrentes, titular, caminho de dados e alternativa offline aparecem no aceite do gate.
