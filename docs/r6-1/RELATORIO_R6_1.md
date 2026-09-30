# Relatório de implementação — JARVIS R6.1

## BASELINE e resultado

R6.1 exige evidência canônica positiva antes de expor, aprovar ou usar qualquer knowledge. A branch isolada `feat/jarvis-unified-r6-1-knowledge-provenance` parte exatamente da candidata R6 `5bd2dd74a35793bf3356fe3b754b34fa21a126cb`. A main informada `8e7c09bb303deb6fe444a3a455961519a5f414d2` é ancestral; a manutenção `a6cd0fffc4207a10462bef853a8994a8fd037c12` não é ancestral. A worktree original R6 estava limpa no SHA congelado. O checkout compartilhado permaneceu em `e648e92467396ce67b75019858fbcd0ee5557042`, branch `feat/gate2.0-e-integracao-web-api`, com quatro arquivos não rastreados preservados (hashes abaixo). A worktree nova está em `/Users/vic/.codex/worktrees/jarvis-r6-1-knowledge-provenance/Jarvis-Victor-OS`.

## Causa e correção

A projeção anterior confundia “não foi reconhecido como `selected_original`” com “é um `skill_derived` aceitável”. Isso era uma confiança por exclusão: links ausentes deixavam a linha sair do verificador de selected source e o endpoint projetava seu conteúdo como `staged`. A auditoria R6 reproduz o vazamento com `UNTRUSTED_R6_AUDIT_KNOWLEDGE_BYTES`.

Agora `kind` é só uma claim que seleciona um verificador explícito. `selected_original` continua exigindo a cadeia relacional completa; `skill_derived` exige missão, execução committed, produtor determinístico, artefato/snapshot/review e eventos correlacionados. Kind desconhecido, linha órfã, campos divergentes ou origem conflitante resultam em conteúdo e hash retidos, decisão recusada e exclusão do contexto/skill. Não foi necessária migração: a evidência do produtor já existe no armazenamento; registros legados sem ela falham fechados.

## Evidência de reprodução e probes

`apps/api/test_knowledge_provenance.py` contém o ataque P1 exato e uma matriz parametrizada de 20 formas de romper a linhagem. O ataque exato confirma quarentena em knowledge, fonte, missão e revisão; decisão HTTP 409; contexto vazio; e ausência dos bytes adversariais no artefato de build-context e na conclusão da missão. O teste positivo confirma que uma captura real do fluxo sintético continua visível como staged, só pode ser aprovada depois da review do artefato e só entra no contexto após uma decisão separada do knowledge.

Na R6 congelada, a reprodução no clone de auditoria terminou com exit 1 no assert esperado: a resposta antiga foi `state=staged`, apesar de o probe exigir `quarantined`, e continha `UNTRUSTED_R6_AUDIT_KNOWLEDGE_BYTES`. Na R6.1, o mesmo ataque passa e o conteúdo é retido em todas as superfícies. O clone antigo de auditoria R2 permaneceu intocado.

## Modelo por origem

Os únicos kinds admitidos pelo schema atual são `selected_original` e `skill_derived`. `origin` e `source_type` não existem em `mission_knowledge`. O campo `state` legado armazena `staged`/`review`; `approved`/`rejected` derivam do ledger. A matriz completa de evidência e capacidades está em `KNOWLEDGE_PROVENANCE.md` e `../r6/TRUSTED_STATE_MATRIX.md`.

## COMANDOS e testes

| Verificação | Resultado/exit code |
|---|---|
| API completa — `rtk env PATH=/tmp/jarvis-r6-uv/bin:/usr/local/bin:/usr/bin:/bin uv run --locked pytest -q` | PASS — 307 passed, 0 failed, exit 0; 2 avisos deprecados |
| Dirigidos R6.1 + R6/R5 | PASS — 70 passed, 0 failed, exit 0; 1 aviso deprecado |
| Vitest — `rtk npm test` | PASS — 16 arquivos/68 testes, exit 0 |
| Typecheck — `rtk npm run typecheck` | PASS — exit 0 após build; tentativa concorrente anterior exit 2 porque `.next/types` estava sendo recriado pelo runner E2E |
| Lint — `rtk npm run lint` | PASS — sem erros/avisos ESLint, exit 0; aviso de depreciação do `next lint` |
| Build — `rtk npm run build` e builds oficiais E2E | PASS — Next.js 15.5.26, exit 0 |
| E2E rodada final 1 — `npm run e2e -- --retries=0` | PASS — 66 passed, 2 skips previstos, 0 retries, exit 0 |
| E2E rodada final 2 — `npm run e2e -- --retries=0` | PASS — 66 passed, 2 skips previstos, 0 retries, exit 0 |
| Larguras | PASS — 320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px; oito rotas, sem overflow/sobreposição |
| Capturas do item retido | `captures/R6_1_KNOWLEDGE_QUARANTINED_desktop.png` e `captures/R6_1_KNOWLEDGE_QUARANTINED_mobile.png`; bytes adversariais não renderizados |
| Breakpoints inspecionados | [320 px](captures/web-r1-missoes-320.png), [390 px](captures/web-r1-missoes-390.png), [767 px](captures/web-r1-missoes-767.png), [768 px](captures/web-r1-missoes-768.png), [1440 px](captures/web-r1-missoes-1440.png) |
| Diff check contra R6 (`5bd2dd7…`) | PASS — exit 0, sem whitespace errors |
| Diff check contra main (`8e7c09b…`) | PASS — exit 0, sem whitespace errors |
| `git fsck --full` | PASS — exit 0, sem erro de objeto; reportou 10 objetos dangling (trees/blobs) |
| Listeners | Nenhum listener de teste em `3000`/`8000`; somente `rapportd:49172` e `Google:[::1]:7679` estavam ativos |
| Worktrees | R1–R6 limpas nos SHAs esperados; R6 original em `5bd2dd7…`; R6.1 limpa após commits; checkout compartilhado permaneceu inalterado nos quatro arquivos não rastreados |
| Quatro SHA-256 do checkout compartilhado | Rechecados ao final e iguais aos valores acima |

Os dois skips por rodada correspondem à separação deliberada dos cenários desktop/mobile do teste visual e foram contabilizados à parte, sem serem tratados como passes.

### Checkout compartilhado — quatro arquivos mantidos

| Arquivo | SHA-256 observado antes da finalização |
|---|---|
| `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md` | `bf32f4a2328eb6da1a6be59785f6bb129e683cbb684256ce718d0336763ca88f` |
| `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md` | `8d16c2c0d70eb19e9bbbe7d458e9045344ec6a82f3845d7a4defb0262314d149` |
| `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` | `f9b6f9337b8da8eee2b5043ccac321f2ec519980701c66cf7cc0e16fb9132715` |
| `package-lock.json` | `928ea8e3b375c204f6307e85f190ac76074dddea2b79fefcda27fcd4ca61afeb` |

## Commits e arquivos

| Commit | SHA completo |
|---|---|
| `fix(api): require positive knowledge provenance` | `aa7df5ed8cba8489adb57546a1097fb3e8633533` |
| `test(api): cover knowledge lineage tampering` | `5a9661e74d1c59b6ec9aa6bed2c5a60b9ddfad0e` |
| `fix(web): label unverified knowledge as withheld` | `bff042d893224e53d6dfd9d68588355c049c9372` |
| `docs(security): define canonical knowledge provenance` | SHA completo da candidata final consta no handoff desta auditoria |

Os arquivos alterados são: `apps/api/source_admission.py`, `apps/api/knowledge_api.py`, `apps/api/test_knowledge_provenance.py`, `apps/web/components/missions/MissionApiPanel.tsx`, `apps/web/lib/knowledge-origin.ts`, `apps/web/__tests__/knowledge-origin.test.ts`, `apps/web/e2e/audit-g5-review-ui.spec.ts`, `docs/r6/TRUSTED_STATE_MATRIX.md`, `docs/adr/010-local-review-trust-boundary.md`, os cinco documentos em `docs/r6-1/` e as capturas em `docs/r6-1/captures/`.

Sem merge, push, tag, deploy ou aceitação formal de G5. A alteração documental de ADR-010 contém somente o esclarecimento de que kind é claim e que toda origem exige prova positiva; a TCB e a fronteira não mudaram.

## Riscos remanescentes

O modelo permanece local e sintético. Ele não fornece autenticidade contra administrador que fabrique um conjunto integralmente coerente de registros no próprio SQLite. Sessões/grants continuam locais e voláteis. Não foram habilitados multiworker, OAuth, integrações reais, LLM, MCP, voz ou uso de dados pessoais. A fronteira ADR-010 não mudou.

## Pendências de autorização e próximo gate

Não há autorização externa pendente para esta implementação. O próximo gate é a auditoria independente da candidata R6.1. A auditoria não representa aceite formal de G5 e não avança para G6.

> G5 permanece sem aceite formal. R6.1 fecha exclusivamente a proveniência positiva de knowledge e não altera a fronteira de confiança ADR-010.
