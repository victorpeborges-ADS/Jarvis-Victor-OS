# JARVIS R4 — relatório da candidata

**Data:** 27/09/2026

**Branch:** `feat/jarvis-unified-r4-2026-09-26`

**Base congelada:** R3 `d26b3a07cc87fcf6a5f92d82f164220ad0089b6d`

**Main esperada:** `8e7c09bb303deb6fe444a3a455961519a5f414d2`

## Escopo e decisão

R4 fecha a admissão de fontes ao catálogo curado, preserva dados legados em quarentena, corrige a contenção da navegação mobile e separa conclusão da missão de decisões humanas anteriores. Esta é uma candidata local para auditoria independente. G5 **não** está formalmente aceito.

## Pré-voo e preservação

- O runner RTK respondeu a `rtk diag-ok` com stdout `[rtk: No such file or directory (os error 2)]`, exit 127. O probe de stdout `rtk printf 'diag-ok\n'` produziu `diag-ok`, exit 0.
- A branch R4 foi criada em worktree exclusiva a partir do SHA R3 congelado. A worktree começou limpa.
- Referências conferidas: R1 `b43f40e6c095461e239e6edb7662d560fcd789a0`, R2 `bb6b78a8631b8e25f18d175178270b6a957fbf86`, R3 `d26b3a07cc87fcf6a5f92d82f164220ad0089b6d`, main `8e7c09bb303deb6fe444a3a455961519a5f414d2` e manutenção `a6cd0fffc4207a10462bef853a8994a8fd037c12`.
- R2 e main são ancestrais de R3 e, portanto, da base inicial R4; a manutenção `a6cd0fffc4207a10462bef853a8994a8fd037c12` não é ancestral.
- O checkout compartilhado está em `feat/gate2.0-e-integracao-web-api` no SHA `e648e92467396ce67b75019858fbcd0ee5557042`. Os quatro arquivos não rastreados permaneceram intactos: `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md`, `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md`, `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` e `package-lock.json`.
- R1, R2 e R3 permaneceram limpas nos SHAs acima; o clone antigo de auditoria R2, já sujo antes desta tarefa, não foi alterado. Main e manutenção foram preservadas nos SHAs acima.
- Worktree R4: `/Users/vic/.codex/worktrees/jarvis-unified-r4-2026-09-26/Jarvis-Victor-OS`, branch `feat/jarvis-unified-r4-2026-09-26`, derivada da base congelada. O fechamento confirma árvore limpa.
- O `node_modules` já instalado em R3 foi ligado temporariamente à R4 para as verificações web e removido ao final; nenhum pacote ou SDK foi instalado.

## Achados e correções

### P1 — proveniência sintética

Antes da correção, a API respondeu HTTP 201 ao texto sintético-desconhecido com `confirm_synthetic=true`. R4 remove esse contrato. `apps/api/fixtures/selected_sources.v1.json` define três fixtures com ID, conteúdo, hash SHA-256, classificação e proveniência. O servidor verifica o catálogo, recebe somente ID/chave de idempotência, grava bytes canônicos e registra a cadeia de revisão/conhecimento na mesma transação.

A migração 0014 reconstrói a tabela preservando os registros: todos entram como `unverified`/`quarantined`; o início da API promove somente os que provam correspondência byte a byte com fixture e snapshot íntegro. Nenhuma decisão humana é criada ou alterada. Leituras, decisões de conhecimento, revisões e contexto validam a prova; revisões não podem reescrever uma fixture.

### P2 — navegação e corrida de revogação

O rótulo “Aprovações” permanece dentro da área interativa e o link mantém altura mínima de 44 px. A regressão mede os limites DOM em 320, 360, 390 e 767 px; confirma que a navegação mobile some a partir de 768 px; e captura também 768, 769, 1024 e 1440 px.

Doze probes cobrem seis leituras (missão, lista/detalhe de revisão, fontes e conhecimento) nas duas ordens da corrida com revogação. A resposta já linearizada pode terminar depois do início da revogação; a revogação aguarda o snapshot sob o lock. Uma leitura que perde a corrida falha com 403.

### Conclusão da missão

Com a guarda original, o teste de jornada terminou em HTTP 422, `conclusão não pode aprovar artefato`, no passo final após uma aprovação humana anterior. A guarda examinava todos os artefatos já aprovados, embora a etapa final criasse apenas um novo rascunho. R4 limita a guarda ao artefato recém-gerado: a execução pode terminar, mas não concede nem muda qualquer decisão de revisão. A jornada completa passa com as aprovações de artefato e conhecimento separadas.

## Ingressos revisados

Foram revistos seleção de fontes, importação de documento `Mission`, revisão/revisão de versões, Inbox DEMO, Calendar simulado e backup/restauração. A importação de `Mission` permanece uma transferência local confirmada; não escreve nas tabelas de fonte ou conhecimento e não alimenta contexto/skills. A revisão de fixture é bloqueada. O mapa completo e os limites estão em [SOURCE_INGRESS_AUDIT.md](SOURCE_INGRESS_AUDIT.md) e [THREAT_MODEL_LOCAL.md](THREAT_MODEL_LOCAL.md).

## Verificações

Resultados finais:

| Suite | Resultado |
| --- | --- |
| `uv run --locked pytest -q` | PASS — 236 testes, 2 warnings |
| Probes G4/G5/R2/R3 + 12 ordens read/revoke | PASS — 74 testes direcionados; inclui 12 combinações de seis rotas e duas ordens |
| Vitest | PASS — 66 testes |
| Typecheck / lint / build | PASS |
| E2E completo, rodada 1 (`npm run e2e -- --retries=0`) | PASS — 64 passaram, 2 ignorados por projeto, zero retries |
| E2E completo, rodada 2 (`npm run e2e -- --retries=0`) | PASS — 64 passaram, 2 ignorados por projeto, zero retries |
| Inspeção visual e medidas DOM | PASS — navegação contida em 320–767 px; desktop a partir de 768 px |
| `diff --check` R3..R4 e main..R4, `core.whitespace=cr-at-eol` | PASS — ambos sem erros |

As duas rodadas E2E gravaram capturas em `captures/round-1/` e `captures/round-2/`. Cada rodada contém vistas desktop em 320, 360, 390, 767, 768, 769, 1024 e 1440 px, além das vistas mobile 320 e 390 px. A medição DOM confirmou que o rótulo e o link permanecem contidos; a 320 px, o link mede 59,2 × 68 px e o rótulo quebra em duas linhas dentro dele. A 390 px, o rótulo cabe em uma linha. Em 768 px e acima, a navegação mobile fica oculta. A inspeção visual comparou mobile e desktop nas duas rodadas.

Uma tentativa inicial de E2E revelou um seletor de revisão desatualizado (`nota-ficticia.md`); ele foi corrigido para o artefato canônico (`tarefas-de-exemplo.md`) antes das duas rodadas completas listadas acima. Os dois testes ignorados são condicionais ao projeto desktop/mobile no teste visual noturno.

## Riscos remanescentes

- O catálogo só prova textos que já estão nele; não detecta PII em texto arbitrário.
- A importação confirmada de uma missão permanece um recurso local de documento e não é uma admissão de fonte. O conteúdo importado fica no escopo da missão, mas não é sintético-verificado nem usado automaticamente por skills/contexto.
- Sessões e concessões são locais, voláteis e coordenadas em um processo. Não habilitar múltiplos workers, API pública, OAuth, contas reais ou dados pessoais.
- Não houve merge, push, tag, deploy ou conexão de conta real. G5 segue pendente de auditoria e aceite formal.
- Os comandos de E2E iniciam e encerram API/web sintéticas com banco temporário; nenhuma porta pública ou serviço persistente foi habilitado.

## Identificação

O SHA completo final de `HEAD` da branch `feat/jarvis-unified-r4-2026-09-26` deve acompanhar este relatório no handoff. A candidata permanece na worktree R4 para revisão independente.
