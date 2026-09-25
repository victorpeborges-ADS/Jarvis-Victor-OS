# Sprint autônoma JARVIS — STATUS

> **Adendo pós-auditoria:** o snapshot da sprint abaixo terminou em `fbaca454`. As correções posteriores estão na branch isolada `feat/jarvis-nightly-stabilization-2026-09-25`; veja [STABILIZATION_REPORT.md](STABILIZATION_REPORT.md) para evidências, testes atualizados, bloqueios e handoff. Gate E continua sem aceite independente.

- Início: 2026-09-25 04:23 UTC (2026-09-25 01:23 BRT).
- Worktree: `/Users/vic/.codex/worktrees/jarvis-autonomous-sprint-2026-09-25/Jarvis-Victor-OS`.
- Branch exclusiva: `feat/jarvis-nightly-2026-09-25-042315`.
- SHA-base verificado: `e648e92467396ce67b75019858fbcd0ee5557042` (`feat/gate2.0-e-integracao-web-api`).
- Escopo: auditoria e correções Gate E sintético; avançar pelos contratos e módulos locais/sintéticos elegíveis; sem dados reais, serviços externos, custo, deploy, merge, tag ou push.
- Estado inicial: Git limpo no worktree; HEAD corresponde ao branch compartilhado antes da criação da branch exclusiva. Tags locais observadas: B, C.1, C.2 e D.
- Inventário de ambiente: Node v26.7.0, npm 11.19.0, uv 0.12.13; `rustc`, Cargo, Gradle e adb indisponíveis no PATH. `uv sync --locked --python 3.12` instalou o runtime fixado pelo projeto; a chamada global `uv run` a partir da raiz usa Python 3.14.3 e não foi usada para executar a API.

## Andamento

- DONE — verificação Git do original e worktree exclusiva criada; nenhuma alteração feita na branch compartilhada.
- DONE — superprompt lido integralmente.
- DONE — documentos canônicos disponíveis lidos: AGENTS, README, Blueprint, PromptPack, arquitetura Gate 2.0, Gate B/B.1/B.2, C.1/C.1.1, C.2, D/D.1 e handoff E. A análise da playlist existia apenas como arquivo não rastreado no repositório original; foi lida em modo somente leitura. Plano mestre omnichannel, consolidação histórica e prompt independente atual do Gate E não existem nesta cópia nem foram encontrados na listagem permitida.
- DONE — baseline: `uv sync --locked --python 3.12`; pytest API 138/138; `npm ci`; Vitest 34/34; typecheck, lint e build Next passaram.
- DONE — E2E Gate E 28/28 passou em Chromium desktop/mobile na origem IPv6 aprovada (`http://[::1]:3000`) e API IPv6 loopback (`http://[::1]:8000`). As portas IPv4 `127.0.0.1:3000` estavam ocupadas por outro workspace e não foram usadas.
- DONE — o E2E revelou que o runner anterior verificava apenas a porta da API, podendo testar um serviço web alheio. `run-e2e.mjs` agora valida ambas as portas, constrói antes de subir serviços, inicia/aguarda seu próprio Next, impede reutilização do servidor do Playwright e mantém subprocessos em loopback com ambiente minimizado. A rota de erro por porta ocupada foi verificada; termina antes do build ou do início da API.
- DONE — novas capturas sintéticas copiadas para `docs/nightly/captures/`; as imagens existentes do Gate 1/E foram restauradas sem alterações.
- DONE — a comparação de passphrase Unicode foi reproduzida (frase correta com acentos resultava em HTTP 500) e corrigida comparando bytes UTF-8 com `hmac.compare_digest`; entrada JSON com surrogate inválido falha sem erro interno nem reflexão.
- DONE — regressão adversarial cruza dois tokens CSRF reais e percorre criação/revogação de grant, classificação, sync e logout com token ausente, inválido, de outra sessão e Origin externa; todos recusados sem alteração do grant.
- DONE — suíte API após correções: 140/140; recorte dos três testes novos/afetados: 3/3. Avisos conhecidos do TestClient/httpx permanecem.
- DONE — E2E repetido depois da correção Unicode e da mudança no destino de capturas: 28/28 passou em Chromium desktop/mobile; as evidências foram gravadas em `docs/nightly/captures/`, sem alterar capturas versionadas fora desse diretório.
- DONE — P1/4A criou contratos JSON Schema v1 para Missão, tarefas, checkpoints, eventos, artefatos, contexto, conhecimento, skills, capabilities, grants de dispositivo, envelope de sync e política de notificações; tipos TS, validação compartilhada por JSON Schema em Python/Ajv, modelo Pydantic da Missão, exemplos sintéticos e ADR 001.
- DONE — P1/4B–4E e P2/5A: Central local com dependências, status, checkpoints, trilha de eventos, falha/retry idempotente, cancelamento, proveniência, revisão local de rascunho e quatro skills determinísticas; ciclo de vida do conhecimento e builder que filtra por grant/escopo/validade/frescor/orçamento. Página Missões em desktop/mobile sem usar API, dados DEMO ou SQLite. ADR 002 descreve limite de `localStorage`.
- PASS — regressões completas executadas após o core: API 146/146, Vitest 48/48, TypeScript, lint e build Next. Os dois exemplos compartilhados são aprovados em Python/Ajv; rejeições cobrem status inválido, orçamento acima de zero, propriedade desconhecida e timestamp sem fuso.
- PASS — E2E completo: 32/32 em Chromium desktop/mobile após o drawer de revisão e a decisão de aprovação local. Execução final: `JARVIS_E2E_WEB_ORIGIN=http://[::1]:3000 JARVIS_E2E_API_ORIGIN=http://[::1]:8000 npm run e2e`; build Next incluído. A execução padrão IPv4 terminou no pré-voo por porta 3000 ocupada por processo de outro workspace; não foi interrompido nem alterado.
- BLOCKED para uso durável/real — a implementação usa `localStorage`, sem transação multiaba/dispositivos; a política exige autorização e migração próprias antes de usar memória SQLite ou dados reais.
- DONE — P3/6B: `IntelligenceRouter` determinístico com `FakeProvider`, orçamento zero, fallback sem provider para qualquer classificação que não seja sintética e envelope de handoff manual. Testes verificam determinismo, privacidade e ausência de transmissão.
- DONE — P3/6C: `FakeWorkflowAdapter` read-only filtra grant antes do domínio e respeita política sintética de interrupção/horário silencioso. Sem n8n, scheduler, webhook ou notificações reais.
- PARTIAL/BLOCKED — P3/6A: ADR documental preliminar compara Cloudflare Workers+D1 e Cloud Run usando documentação oficial atual. PoC/benchmark nos adapters de provedores não foi executado; compatibilidade, custo de conta, recuperação e região permanecem não provados. Nenhuma plataforma escolhida.
- PARTIAL/BLOCKED — P2/5C: scaffold React/Vite + Tauri 2 em `apps/desktop`; frontend `npm run build` passou. Commit `1dd3c6c`. Rust/Cargo ausentes; **binário Tauri NÃO COMPILADO**, `.app` não gerado; nenhum toolchain foi instalado.
- PARTIAL/BLOCKED — P2/5D: shell React/Vite + Capacitor, projeto Android gerado/sincronizado; outbox sintética local limitada a 20 itens. Vitest 2/2, Playwright 4/4 desktop/mobile, lint/build e auditoria npm sem vulnerabilidades. Android Studio/SDK/Gradle/adb ausentes; **APK NÃO COMPILADO** ou instalado; nenhum toolchain foi instalado.
- PASS — suíte final: API 146/146; Vitest 53/53; TypeScript, lint e build Next/E2E aprovados. Avisos existentes: depreciação Starlette/httpx e aviso de retirada futura de `next lint`; Node informou depreciação de `module.register()` na execução Playwright.
- DONE — capturas de página longa agora removem temporariamente a navegação fixa no teste, sem alterar a interface. Após ajuste, cenário de missão/captura passou 1/1 desktop e 1/1 mobile; a suíte completa 32/32 foi executada antes dessa alteração apenas de screenshot.
- DONE — entregáveis matinais: `EXECUTIVE_REPORT.md`, `TEST_MATRIX.md`, `GATE_E_AUDIT_AND_FIXES.md`, `APPROVAL_REQUESTS.md`, `RESUME.md` e `DEMO.md`. Gate E continua `IMPLEMENTADO/TESTADO LOCALMENTE — AUDITORIA INDEPENDENTE PENDENTE`; nenhuma aceitação foi declarada.
- Não havia segundo agente revisor disponível nesta execução; nenhuma auditoria independente foi simulada pelo implementador.
- DONE — scaffold Android e suíte web testados/sincronizados e commitados em `5925e5f`; nenhum build nativo executado.
- Commits da sprint na branch isolada: runner `b9151af`; passphrase `3ed519e`; capturas E2E `a32277e`; contratos `2612832`; Missões/skills `c01ef73`; router/observadores `56432e6`; ajuste de capturas `08ab532`; relatório `cb4f261`; desktop `1dd3c6c`; Android `5925e5f`.
- Relatórios finais foram atualizados após os scaffolds desktop e Android. Commits nativos `1dd3c6c` e `5925e5f`; relatórios finais seguem em commit documental separado.
- Próxima ação recomendada: auditor independente read-only; depois resolver catálogo de calendários e concorrência/revogação antes de qualquer dado real. Missões seguem apenas em `localStorage` até decisão e migração autorizada.

## Evidências provisórias

- Primeira tentativa E2E na configuração herdada: interrompida após comprovar que a porta IPv4 3000 pertencia a outro workspace; os resultados dessa tentativa não são aceitação de teste. Somente os processos iniciados por esta sessão foram encerrados.
- Tentativa isolada nas portas 39941/49941: 24 testes DEMO/desktop/mobile passaram; 4 testes de integração falharam no login porque a política canônica rejeita corretamente origens fora das portas 3000/8000. O teste subsequente IPv6, dentro do contrato existente, passou 28/28.
- A API não foi aberta no banco padrão. O E2E criou e removeu seu banco SQLite sintético temporário.

## Atualização de estabilização — worktree candidata

- A branch `feat/jarvis-nightly-stabilization-2026-09-25` deriva do commit auditado `fbaca45446f31258e7a121b3a49284516fcc8243` em worktree independente. O checkout da sprint original permaneceu intacto.
- Corrigidos os bloqueadores reproduzidos para uma nova revisão: handshake HMAC de posse da API no runner E2E; validação de timestamp/contexto; quarentena completa de Missões inválidas com recuperação; catálogo Calendar limitado por grant; leitura e revogação linearizadas no mesmo processo; permissão Tauri incoerente removida; comparação de fontes integrada apenas após minimização local.
- Reteste final: API 149/149; web Vitest 63/63, typecheck, lint e build; browser E2E 36/36 desktop/mobile; mobile unit 2/2, E2E 4/4, lint e build; desktop build. Detalhes no [STABILIZATION_REPORT.md](STABILIZATION_REPORT.md) e adendo da [TEST_MATRIX.md](TEST_MATRIX.md).
- Parecer das correções locais: PASS sintético. Parecer de encerramento do Gate E: BLOCKED até auditoria independente do commit final. Dados reais e múltiplos processos continuam bloqueados; binários Tauri/APK não foram gerados.
- Probe da passphrase Unicode antes da correção: HTTP 500 para frase configurada/fornecida com `é`; após correção, 201 para a frase correta e 422 genérico para uma sequência Unicode inválida.
