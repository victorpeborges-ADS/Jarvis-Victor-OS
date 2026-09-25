# Parecer independente — Gate 2.0-E e estabilização Nightly

**Auditoria somente leitura do commit congelado.** A worktree auditada e o checkout original não foram modificados. Não houve merge, push, tag, deploy, conta real, API paga nem listener público.

## Baseline

| Item | Valor observado |
|---|---|
| Worktree auditada | `/Users/vic/.codex/worktrees/jarvis-nightly-stabilization-2026-09-25/Jarvis-Victor-OS` |
| Branch | `feat/jarvis-nightly-stabilization-2026-09-25` |
| HEAD | `ee5fc29220bbd594f5456ae51ed07f7e2e1fabd5` |
| Árvore | limpa (`git status --porcelain` vazio) |
| Nightly anterior | `fbaca45446f31258e7a121b3a49284516fcc8243` é ancestral |
| Baseline Gate E | `e648e92467396ce67b75019858fbcd0ee5557042` é ancestral |
| Cópia isolada | `/tmp/jarvis-audit-ee5fc29` (archive do commit, sem `.git`) |
| Checkout original | continua em `feat/gate2.0-e-integracao-web-api` @ `e648e924`; os três arquivos não rastreados já existentes não foram tocados |
| Processo alheio | `next-server` PID 72694 em `*:3000` IPv6 permaneceu vivo antes e depois do E2E |

O E2E oficial desta auditoria usou `127.0.0.1:3000` e `127.0.0.1:8000`, banco SQLite temporário do runner e capturas em `/tmp/jarvis-audit-captures`. O processo 72694 não foi encerrado.

## Pareceres

| Escopo | Parecer | Limite |
|---|---|---|
| Gate 2.0-E, local e sintético, um processo | **PASS** | Integração web/API, sessão, grants, DEMO separado, catálogo simulado e runner com prova HMAC. Não autoriza dado pessoal, conta real nem API pública. |
| Correções da estabilização Nightly | **PASS** no mesmo limite | HMAC, contexto, quarentena de Missões, catálogo por grant, linearização da revogação no processo e remoção de `opener:default` foram reproduzidos fora da suíte do implementador. |
| Dados pessoais, hospedagem remota, vários processos | **BLOCKED** | Grants e sessões continuam memória de um processo. Revogação em outro processo não existe. |
| Binários Tauri e APK | **BLOCKED / NÃO VERIFICADO** | Não há `rustc`, Cargo nem Gradle. Só o bundle web dos scaffolds foi compilado. |

## Matriz

| Verificação | Comando | Resultado | Evidência |
|---|---|---|---|
| Prova HMAC, servidor 200 falso, prova inválida, prova reaproveitada, corrida de porta, processo vivo | script Node em portas efêmeras, importando `e2e-api-readiness.mjs` | **PASS** 7/7 | Falha de posse lança erro e não mata o filho; filho morto é recusado; HMAC válido do nonce corrente é aceito |
| HMAC Python = verificador Node | `TestClient` `/health` + `matchesReadinessProof` | **PASS** | Sem `JARVIS_E2E_READY_TOKEN` não há header; com token, a prova muda se o nonce muda |
| Runner com falha | `node scripts/run-e2e.mjs` antes do `npm ci` | **exit 1** | Build ausente termina não zero; PID 72694 intacto |
| Autorização independente | `pytest test_audit_independent_probe.py` | **PASS** 4/4 | Sessão ausente/expirada, CSRF, Origin, Host, grant por domínio, ID, briefing, DEMO/API, catálogo |
| Catálogo, sync e logout | script TestClient avulso | **PASS** | Sem grant: catálogo 403, sync 403, state 200 com lista vazia. Classificar domínio não concedido: 403. Logout sem CSRF: 403. Depois do logout: 401 |
| Corrida leitura/revogação, um processo | probe com pausa dentro de `list_authorized_events` | **PASS** | A revogação espera o lock; a leitura que entrou antes devolve o evento; a seguinte recebe 403 |
| Vários processos | `multiprocessing` lendo `_grants` | **PASS da limitação** | O filho vê 0 grants enquanto o pai tem 1. Não há coordenação entre processos |
| Contexto e Missões | `vitest run __tests__/audit-independent.test.ts` | **PASS** 3/3 | Timestamp inválido, NaN, futuro, expirado, domínio fora, relógio adiantado, payload hostil só como dado, original preservado se a quarentena não grava |
| pytest oficial | `uv run --locked pytest -q --ignore=test_audit_independent_probe.py` | **PASS** 149/149 | Dois avisos já conhecidos: Starlette/httpx e cookies do TestClient |
| Vitest oficial | `vitest run` excluindo o probe | **PASS** 63/63 em 13 arquivos | Inclui o teste de readiness do implementador |
| typecheck | `tsc --noEmit` em `apps/web` | **PASS** | |
| lint web | `npx next lint` isolado | **PASS** exit 0 | “No ESLint warnings or errors”; aviso de depreciação do `next lint` |
| build web | `npm run build` | **PASS** | Next 15.5.26, 11 páginas estáticas |
| E2E web desktop/mobile | `npm run e2e` com origens `127.0.0.1` | **PASS** 36/36 em 1,6 min, **exit 0** | Runner oficial, API filha, SQLite temporário, Chrome do sistema |
| desktop | `npm run build` | **PASS** do bundle Vite | App Rust **não** compilado |
| mobile | `npm test`, `oxlint`, `npm run build` | **PASS** 2/2, lint 0, Vite ok | |
| mobile browser | `npm run e2e` com Chromium local em 5173 | **PASS** 4/4 | A primeira tentativa falhou só porque o browser do Playwright não estava baixado; não é defeito do produto. APK não gerado |
| Tauri `opener` | capabilities + Cargo | **removido** | Só `core:default`. Nenhuma ocorrência de `opener` |
| Instalação | `uv sync --locked --python 3.12`; `npm ci` em web, desktop e mobile | **PASS** | Feito só na cópia |

## Achados

### P0

Nenhum.

### P1

Nenhum no escopo local, sintético e de um processo. O que seria P1 para dado real está na seção proibida, não como falha deste aceite.

### P2

1. **`GET /real/calendar-sim/state` sem grant responde 200 com `states: []`.** Catálogo e sync no mesmo estado respondem 403. A resposta vazia não devolveu calendário classificado. Reproduzir: login sintético e GET `/real/calendar-sim/state` antes de criar grant. Corrigir antes de um conector real, para a ausência de concessão ser sempre 403.

2. **Metadados de calendário ainda não classificado aparecem para qualquer grant Calendar.** Depois de classificar só `sim_calendar_a` em `dom_synthetic_a`, o catálogo devolveu 8 itens. É o contrato sintético descrito na estabilização (metadado para escolher o domínio). Num Calendar real, o nome de um calendário ainda não mapeado vazaria para qualquer concessão Calendar. Não usar esse comportamento com conta real.

3. **GET autenticado aceita ausência de `Origin` e recusa `Origin` externo.** Probe: `/real/events` sem Origin, com grant, 200; com `https://evil.example`, 403. Adequado ao loopback de um usuário. Insuficiente se o serviço sair da máquina.

### P3

1. **Pré-voo de porta não é posse.** `assertPortAvailable` em `127.0.0.1:3000` passou enquanto o PID 72694 escutava em IPv6 `*:3000`. O `bind` Python em `127.0.0.1:3000` retornou `EADDRINUSE`; o `listen` exclusivo do Node passou. A prova HMAC recusou 200 sem prova, prova inválida e prova de outro nonce. O E2E real subiu em `127.0.0.1:3000` e o PID 72694 continuou vivo. A posse efetiva é o HMAC, não o pré-voo.

2. **Bytes já linearizados não são recolhidos.** A leitura que segura o lock termina com o snapshot autorizado; a revogação espera e só vale para a leitura seguinte. Isso foi reproduzido. Não há garantia depois que a resposta saiu do lock, nem entre workers.

3. **`visible_domains` vazio faz `calendar_grant_guard` passar** (`conjunto vazio <= qualquer conjunto`). Combinado com o item P2.1, um state vazio pode ser devolvido mesmo se a concessão cair entre o filtro e o lock. Sem linhas, não há vazamento de evento.

4. Avisos de depreciação Starlette/httpx, `next lint` e `module.register()` do Playwright. Não alteram o resultado.

## Semântica de concorrência

No mesmo processo, `_grant_lock` é um `RLock`. Autorização e `list_authorized_events` ocorrem dentro desse lock. A revogação iniciada no meio da consulta ficou bloqueada até `release`; a resposta da leitura foi 200 com `real_evt_audit_a`; o GET seguinte foi 403.

Entre processos, o dicionário `_grants` não é compartilhado. Um filho iniciado depois do `put_grant_for_tests` no pai observou zero concessões. Não foi levantado Uvicorn com vários workers, de propósito: isso seria outro listener e não acrescentaria coordenação que o código não tem. O que permanece inseguro: dois workers aceitariam sessões e grants independentes; revogar num deles não corta a leitura do outro. Sessões também morrem com o processo.

## Classificação de escopo

| Componente | Classe | O que foi verificado |
|---|---|---|
| Missões no browser | **PARCIAL** | Fluxo sintético integrado e E2E de recuperação. Persistência é `localStorage`, não SQLite, sem sync entre abas |
| Skills sintéticas | **PARCIAL** | Captura, contexto, comparação e rascunho são determinísticos e locais. `compare-sources` só vê o que o filtro cliente já incluiu |
| Ciclo de conhecimento | **SCAFFOLD** | `transitionKnowledge` não tem call site de produção; só testes |
| Context builder | **PARCIAL** | Minimização no cliente. Um `client_visible_*` forjado inclui o texto. A API, sem grant, responde 403 para evento, ID, briefing, catálogo e sync |
| Shell desktop | **SCAFFOLD** | `tsc && vite build` passou. Binário Tauri não compilado. Permissão `opener` ausente |
| Shell Android | **SCAFFOLD** | Vite, 2 testes unitários e 4 E2E de browser passaram. Manifest tem `INTERNET`. APK não gerado |
| Builds nativos | **BLOCKED** | Sem Rust/Cargo/Gradle. **NÃO VERIFICADO** como aplicativo instalável |

Texto hostil no contexto saiu dentro de `JSON.stringify`, prefixado como dado. Não houve `eval`, `new Function` nem `dangerouslySetInnerHTML` em `apps/web/lib` nem na página de Missões.

## O que continua proibido

Antes de dados pessoais, institucionais ou de saúde, e antes de qualquer hospedagem que não seja o loopback desta máquina:

- OAuth, cliente Google, Calendar real, Gmail, Drive, LLM, n8n real, webhook, túnel, porta pública, deploy.
- Gravar Missões, conhecimento ou sessão no SQLite de uso real, ou copiar fixture DEMO para essa base.
- Tratar `domain_id`, rótulo A–H ou `client_visible_*` como autorização.
- Subir exame, extrato ou dado clínico.
- Considerar o catálogo simulado seguro para listar calendários reais.
- Rodar mais de um worker enquanto grants e sessões forem memória do processo.
- Gerar ou distribuir `.app` ou APK sem toolchain revisada e nova auditoria de permissões.
- Merge em `main`, tag, push ou ativação remota com base só neste parecer.

## Condições para integrar os commits

Integração aqui significa trazer a branch para revisão humana. Não significa merge feito por esta auditoria.

1. O SHA integrado tem de ser `ee5fc29220bbd594f5456ae51ed07f7e2e1fabd5`, ou um descendente cujo diff contra esse SHA seja só documentação deste parecer. Os ancestrais obrigatórios são `e648e924` e `fbaca454`.
2. A worktree de origem permanece `feat/jarvis-nightly-stabilization-2026-09-25`, limpa, sem amend dos commits já auditados.
3. O aceite humano precisa separar três decisões: Gate E sintético local; correções Nightly; scaffolds desktop/Android e Missões em `localStorage`. Este parecer aceita as duas primeiras nesse limite e classifica a terceira como scaffold/parcial.
4. Não criar tag de aceite real, não fazer push e não apontar o serviço para fora de `127.0.0.1`/`::1`.
5. Antes de qualquer dado real, um gate novo precisa tornar a concessão transacional entre processos, devolver 403 no state sem grant, e revisar o catálogo para não expor calendário não mapeado.
6. Os três arquivos não rastreados do checkout original (`SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md`, `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md`, `package-lock.json`) não fazem parte deste commit e não devem entrar no mesmo merge.

## Conclusão

O commit `ee5fc29` fecha, em evidência reproduzida, o Gate 2.0-E **somente** como integração local e sintética de um processo. As correções Nightly que este escopo pedia estão tecnicamente aceitas. Isso não torna a API apta a dado pessoal nem a hospedagem remota. Binários nativos não foram verificados.
