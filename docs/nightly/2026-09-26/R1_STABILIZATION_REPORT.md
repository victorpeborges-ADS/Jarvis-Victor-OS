# R1 — relatório de estabilização

**Estado:** candidata para auditoria independente; sem merge, push, tag ou deploy.
**Data:** 2026-09-26
**Branch R1:** `feat/jarvis-unified-r1-2026-09-26`
**Worktree R1:** `/Users/vic/.codex/worktrees/jarvis-unified-r1-2026-09-26/Jarvis-Victor-OS`

## Baseline e pré-voo

| Item | Verificação |
|---|---|
| Candidata de origem | `feat/jarvis-overnight-unified-2026-09-26` em `cfa19bbbd5101f2758b6d87c68d545ab8d252a7b` |
| `main` | `8e7c09bb303deb6fe444a3a455961519a5f414d2`, sem alteração |
| Ancestralidade da manutenção | `a6cd0ff` não é ancestral de `cfa19bb` (`merge-base --is-ancestor` exit 1) |
| Limpeza da candidata congelada | Checkout confirmado limpo no pré-voo em `cfa19bb`; no inventário final o caminho deixou de existir, embora o ref da branch continue no mesmo SHA |
| Executor | `rtk proxy sh -c 'printf "executor-stdout-ok\\n"; rc=$?; printf "exit=%s\\n" "$rc"; exit "$rc"'` — stdout `executor-stdout-ok`, `exit=0`, exit code 0 |
| Worktree criada | Branch R1 criada diretamente de `cfa19bbbd5101f2758b6d87c68d545ab8d252a7b`; branch de origem continua apontando para esse SHA |

No inventário final, o caminho original informado `/Users/vic/.codex/worktrees/jarvis-overnight-unified-2026-09-26/Jarvis-Victor-OS` não existia e não constava em `git worktree list`; o ref Git da candidata original continuava em `cfa19bb`. Não criei nem substituí um checkout nesse caminho. A worktree R1 foi a única nova worktree criada por esta tarefa.

O checkout compartilhado `/Users/vic/Freela/Jarvis-Victor-OS` permaneceu na branch `feat/gate2.0-e-integracao-web-api`, commit `e648e92467396ce67b75019858fbcd0ee5557042`. Seus quatro arquivos não rastreados foram preservados com estes hashes SHA-256:

| Arquivo | SHA-256 |
|---|---|
| `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md` | `bf32f4a2328eb6da1a6be59785f6bb129e683cbb684256ce718d0336763ca88f` |
| `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md` | `8d16c2c0d70eb19e9bbbe7d458e9045344ec6a82f3845d7a4defb0262314d149` |
| `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` | `f9b6f9337b8da8eee2b5043ccac321f2ec519980701c66cf7cc0e16fb9132715` |
| `package-lock.json` | `928ea8e3b375c204f6307e85f190ac76074dddea2b79fefcda27fcd4ca61afeb` |

## Correção A — IDs de evento repetidos na importação

### Reprodução e causa raiz

O probe independente cria uma missão pela API, lê o documento persistido e copia `mission`. Na cópia, muda somente `document["id"]` para um ID de missão novo (`mission_import_dup_event_01`); os IDs dos eventos continuam iguais aos já gravados. O POST reproduzível é `/real/missions/import`, com `{ "missions": [documento_copiado], "idempotency_key": "duplicate-event-import", "confirm": true }`. A colisão é entre missões: não é um replay da mesma missão, nem uma duplicação criada dentro do lote. O payload do evento reaproveitado é o mesmo da missão de origem; o ID de missão diferente faz o import tentar criar outro vínculo para aquele ID global.

Em `migrations/0006_missions.sql`, `mission_events.id` é chave primária global; `UNIQUE (mission_id, idempotency_key)` cobre uma segunda identidade local à missão. A idempotência da requisição de importação é única por `(owner, idempotency_key)`. A transação `BEGIN IMMEDIATE` reverte a tentativa inteira quando a constraint global falha, mas a rota antiga deixava a colisão chegar ao tratamento genérico de erro e devolvia HTTP 503. A auditoria observou que nem a missão nem a chave de idempotência eram gravadas.

### Semântica implementada

- IDs de evento repetidos no mesmo documento são inválidos para aquele documento: ele permanece na quarentena explícita do contrato de importação parcial (HTTP 200 com índice e motivo; sem inserção silenciosa).
- IDs de missão ou de evento repetidos entre documentos válidos do mesmo lote rejeitam o lote com HTTP 422 antes de qualquer escrita.
- ID de missão já persistido com o mesmo proprietário e documento canônico idêntico é repetição idempotente sem nova escrita. O mesmo ID com conteúdo diferente, ou pertencente a outro principal, retorna HTTP 409 genérico.
- ID de evento já persistido sob outra missão retorna HTTP 409 genérico, tanto com conteúdo de evento igual como diferente e também quando pertence a outro principal. A resposta não contém IDs, proprietário ou documento de origem.
- O import pré-valida conflitos persistidos dentro da transação antes de inserir qualquer documento. A transação preserva atomicidade; não se captura nem se suprime `IntegrityError` como estratégia de sucesso.

Foram adicionadas dez provas no módulo novo, cobrindo duplicações no lote, duplicação no documento, repetição sucessiva idêntica, alteração de conteúdo, colisão de evento persistida com conteúdo igual/divergente, principal distinto, resposta perdida depois do commit com retry após reinício, corrida de dois imports conflitantes e corrida de replay com a mesma chave. Em concorrência, há um vencedor e um HTTP 409; no retry idêntico, há uma escrita e uma resposta marcada como replay.

## Correção B — layout em 768 px

Na captura independente, em 768 px o campo de comando do cabeçalho era comprimido pelo `flex` e quebrava o texto em várias linhas, sobrepondo as ações. O grid da tela `/missoes` ativava duas colunas em `md`: o formulário fixo de 300 px deixava o cartão vazio estreito no espaço restante. A mesma fronteira `md` em `/fontes` colocava três cartões de conectores lado a lado e produzia overflow em 768 px.

O cabeçalho agora mostra um botão de pesquisa acessível de 44 × 44 px abaixo de `xl`; o texto completo e atalho permanecem em uma linha a partir de `xl`. O estado compacto de `/integrado` também conserva rótulo acessível. O grid de Missões e a grade de conectores de Fontes passam a três colunas somente em `lg` (1024 px), com `minmax(0,1fr)` na coluna fluida de Missões.

O teste visual mede dez larguras — 320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px — em oito rotas principais (`/`, `/conversa`, `/inbox`, `/dominios`, `/aprovacoes`, `/fontes`, `/missoes` e `/integrado`). Nos 80 pares rota/largura, verifica scroll horizontal, limite do `main`, sobreposição no cabeçalho, controles fora da viewport e tabelas sem contêiner rolável; abaixo de 768 px também exige cinco alvos de navegação de pelo menos 44 × 44 px. As oito rotas não renderizam atualmente `<table>` ou `[role=table]`; portanto não havia tabela extensa para exercer, mas o teste deixa a regra de overflow própria preparada para tabelas futuras.

## Capturas

As duas imagens mostram `/missoes` no estado DEMO vazio, a 768 px de largura. O PNG de origem tem 768 × 901 px; a captura R1 foi feita diretamente no viewport de 768 × 900 px antes da captura de página inteira.

- [Antes — reprodução da candidata congelada](r1-captures/R1_MISSOES_768_ANTES.png) — SHA-256 `f4bf4df5d17432a3df407a9759558340e9feebab86d5a0392bcc6740772500b7`.
- [Depois — captura da verificação R1](r1-captures/R1_MISSOES_768_DEPOIS.png) — SHA-256 `d2556eacce54bf6670a19c82633c4f9320de93753286f16dfbe4072a5bf303b9`.

## Regressão e demonstração

| Verificação | Resultado |
|---|---|
| API completa — `uv run --locked pytest -q` | 208 passed, 2 warnings, exit 0 |
| Probes adversariais G4/G5 — `test_mission_engine.py test_mission_auth_races.py test_review_api.py test_knowledge_api.py test_mission_import_identity.py` | 43 passed, 1 warning, exit 0 |
| Vitest — `npm test -- --run` | 66 passed em 15 arquivos, exit 0 |
| TypeScript — `npm run typecheck` | PASS, exit 0 |
| Lint — `npm run lint` | PASS, exit 0; somente aviso de depreciação do comando Next lint |
| Build web — `npm run build` | PASS, exit 0; 11 páginas estáticas geradas |
| E2E completo final 1 — `unset CI; JARVIS_E2E_SCREENSHOT_DIR=… npm run e2e` | 54 passed, 2 skipped, exit 0; sem retries |
| E2E completo final 2, consecutivo — mesmo comando | 54 passed, 2 skipped, exit 0; sem retries |
| Captura visual desktop final | 1 passed; matriz de dez larguras e capturas produzidas |
| Navegação mobile “Mais” | 1 passed isolado e executado também no par E2E completo |
| Teclado responsivo desktop/mobile | 2 passed isolados |
| Integração mobile após sincronizar o probe de revogação | 1 passed isolado e passou no par E2E completo final |
| `git -c core.whitespace=cr-at-eol diff --check` | PASS nos commits atômicos; repetir no estado final após o commit deste relatório |

Os dois skips complementares continuam como skips e não são declarados aprovados: (1) `QA visual noturna: dez larguras sem overflow e sobreposição nas telas principais` é intencionalmente ignorado no projeto mobile (`test.skip` no início do caso); executa e passa no projeto desktop; (2) `navegação mobile Mais mantém áreas acessíveis por teclado` é intencionalmente ignorado no projeto desktop; executa e passa no projeto mobile. Cada execução ignorada permanece ignorada, sem ser contabilizada como PASS.

A primeira execução integral de estabilização também mostrou que o teste de teclado selecionava os dois botões responsivos pelo rótulo, inclusive o oculto; o locator foi ajustado para `getByRole`, que seleciona o controle acessível visível, e os projetos desktop/mobile passaram. Uma repetição adicional revelou uma corrida só no teste E2E de integração: a leitura automática após criar a concessão podia receber o 403 da revogação de teste antes do clique manual. O teste agora aguarda a leitura autorizada HTTP 200 antes da revogação externa e mantém a prova manual de HTTP 403 e limpeza de dados. A prova isolada e as duas rodadas finais passaram. Nenhuma lógica de autenticação/API de produção foi alterada para contornar essa corrida.

As jornadas `G5 UI: resposta perdida é reconciliada com estado canônico`, `aprovação persistente de artefatos na API local sintética (G5)` e `G6 UI: arquivo fictício escolhido entra somente após duas aprovações` passaram em desktop e mobile nas rodadas completas. A seleção fictícia entra pela web na API local, persiste no SQLite sintético, passa pela revisão explícita e só integra o contexto depois das decisões separadas. O modo web DEMO continua separado; a interface não declara contas reais conectadas.

## Commits atômicos e SHAs

| Commit | SHA completo | Conteúdo |
|---|---|---|
| `fix: validate mission import identity conflicts` | `141eaa371f451227c9bbcb45f092abad0698f35a` | Validação, conflito e testes API de identidade/idempotência |
| `fix: keep mission layout readable on tablets` | `1cf1e015da2cf1dadb087434c155658ce2952da5` | Cabeçalho, breakpoints, matriz visual e capturas |
| `test: serialize synthetic grant revocation check` | `d134b8fcaa2fd10a8e578609ad70925b882cdf53` | Sincronização determinística do probe E2E de revogação |

**SHA R1 de código e testes verificados:** `d134b8fcaa2fd10a8e578609ad70925b882cdf53`, descendente direto da candidata congelada. Este relatório será acrescentado em commit documental seguinte; o HEAD completo da branch após esse commit consta no handoff final.

## Riscos e limites residuais

- A detecção de eventos globais foi testada com SQLite e concorrência em um processo. Não amplia o aceite para multiworker ou serviços externos.
- A tela `/fontes` não contém tabelas extensas no estado atual; a política é verificada pelo teste quando tabelas forem introduzidas.
- A captura auditada mede 768 × 901 px e a nova captura direta do viewport mede 768 × 900 px; ambas têm largura CSS de 768 px e mesma rota/estado.
- O caminho da worktree original e o bundle `JARVIS.app` não estavam disponíveis no inventário final. Nenhum bundle foi recompilado nem declarado verificado nesta tarefa; nenhum APK/SDK Android foi gerado ou instalado.
- Permanecem pendentes auditoria independente desta R1 e aceite humano do G5. Não iniciar outro gate até essa revisão.

## Próximo passo

Entregar esta branch e o presente relatório para auditoria independente R1. Não fazer merge, push, tag, deploy ou conexão com contas reais.
