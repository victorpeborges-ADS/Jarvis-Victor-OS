# JARVIS R5 — relatório da candidata

## Identificação

- Branch: `feat/jarvis-unified-r5-2026-09-27`.
- Baseline R4 congelada: `59d8598cf733f9db4c7f6ca31c1b3b2bc7b8d03e`.
- SHA final R5: será informado no handoff, após o commit deste relatório.
- Main de comparação: `8e7c09bb303deb6fe444a3a455961519a5f414d2` (conferido no fechamento).
- Aceite formal G5: **não declarado**.

## Git e preservação

R5 foi aberta em worktree exclusiva diretamente sobre o SHA R4 congelado. Os probes `git merge-base --is-ancestor` retornaram exit code `0` para R4→R5 e main→R5. Os commits atômicos de código/API e UX/evidências são `f8b61d12f044c6fbb2793f89d7ad2399e6f5cd36` (`fix: validate source trust and local review claims`) e `73d94f482af0158222796181dd4820fc5ab07d0d` (`fix: keep mobile approval navigation readable`).

O checkout compartilhado permaneceu em `feat/gate2.0-e-integracao-web-api`, SHA `e648e92467396ce67b75019858fbcd0ee5557042`. Os quatro arquivos não rastreados mantiveram os mesmos hashes SHA-256 antes/depois: `PROMPT_JARVIS_G3_MISSOES_PERSISTENTES_P2.md` (`bf32f4a2328eb6da1a6be59785f6bb129e683cbb684256ce718d0336763ca88f`), `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md` (`8d16c2c0d70eb19e9bbbe7d458e9045344ec6a82f3845d7a4defb0262314d149`), `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` (`f9b6f9337b8da8eee2b5043ccac321f2ec519980701c66cf7cc0e16fb9132715`) e `package-lock.json` (`928ea8e3b375c204f6307e85f190ac76074dddea2b79fefcda27fcd4ca61afeb`).

R1/R2/R3/R4 continuaram limpas, respectivamente nos SHAs `b43f40e6c095461e239e6edb7662d560fcd789a0`, `bb6b78a8631b8e25f18d175178270b6a957fbf86`, `d26b3a07cc87fcf6a5f92d82f164220ad0089b6d` e `59d8598cf733f9db4c7f6ca31c1b3b2bc7b8d03e`. O clone de auditoria antigo em modo detached foi deixado intocado. O commit de manutenção `a6cd0fffc4207a10462bef853a8994a8fd037c12` continua resolvível e não foi movido.

## Objetivo e decisão

Fechar as alegações de proveniência/decisão identificadas em R4, manter a autorização local, normalizar importações de revisão sem confiar em estados enviados pelo cliente e reduzir a quebra do rótulo móvel de Aprovações. A decisão técnica está em [ADR-009](../adr/009-trusted-source-and-review-state.md).

## Alterações

- Revalidar fontes selecionadas a partir do catálogo do servidor, missão, domínio, knowledge, snapshot e ledger antes de expor conteúdo ou estado.
- Rebaixar e ocultar registros cujas ligações ou bytes não provam origem; preservar o registro em quarentena.
- Derivar estado de revisão do snapshot e ledger; não tratar string importada como aprovação.
- Normalizar estados neutros de importação a rascunho e rejeitar decisão importada sem ledger.
- Adicionar migração 0015, probes e fixtures de upgrade sintéticas.
- Ajustar label Aprovações em viewport estreito e estender a suíte responsiva.

Arquivos de implementação: `apps/api/source_admission.py`, `selected_source_api.py`, `knowledge_api.py`, `mission_repository.py`, `mission_api.py`; migração `0015_selected_source_reconciliation.sql`; testes de API `test_r5_trusted_state.py`, `test_memory_store.py`, `test_selected_source_api.py`; fixtures de estados de migração sintéticos em `apps/api/fixtures/migration_states/`. UX: `apps/web/components/ui/BottomNav.tsx` e `apps/web/e2e/r4-responsive-navigation.spec.ts`. Contrato, ameaça, compatibilidade, matriz, retomada, relatório e capturas ficam em `docs/adr/009-trusted-source-and-review-state.md` e `docs/r5/`.

## Segurança e limites

Sessões e grants seguem locais e voláteis. O modo de operação continua loopback e single-process. Sem OAuth, multiworker, API pública, dados pessoais, contas reais ou escrita externa. Ameaças e riscos estão em [THREAT_MODEL_LOCAL.md](THREAT_MODEL_LOCAL.md). G5 não foi formalmente aceito.

## Evidências

O preflight emitiu stdout `R5 final verification stdout` e exit code `0`. A primeira tentativa de `pytest` foi iniciada no diretório raiz, fora do projeto `apps/api`; por isso não carregou o lockfile e a coleta parou por incompatibilidade de Starlette. A execução oficial, dentro de `apps/api`, passou.

| Suite | Resultado |
| --- | --- |
| `cd apps/api && uv run --locked pytest -q` | PASS — 265 testes, 2 avisos de depreciação, 56,14 s |
| Probes direcionados de proveniência, migração, revisões, conhecimento, revogação e sessão | PASS — 177 testes, 2 avisos, 32,16 s |
| Web Vitest | PASS — 66 testes em 15 arquivos |
| Web typecheck / lint / build | PASS |
| Mobile Vitest / lint / build | PASS — 2 testes; lint e build verdes |
| E2E completo, rodada 1 (`npm run e2e -- --retries=0`) | PASS — 64 passaram, 2 skips condicionais de projeto, sem retries |
| E2E completo, rodada 2 (`npm run e2e -- --retries=0`) | PASS — 64 passaram, 2 skips condicionais de projeto, sem retries |
| Revisão visual | PASS — capturas desktop e mobile nos dez breakpoints (320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px); inspeção detalhada dos limites de 320/390/767/768/769/1024/1440 px |
| `git diff --check` R4..R5 e main..R5 | PASS — sem erros |

As capturas comparativas R4/R5 estão em [CAPTURAS.md](CAPTURAS.md). Na captura R4 a 320 px, “Aprovações” quebra em duas linhas; em R5 cabe em uma linha com fonte de 12 px dentro do controle. A captura R5 em 768 px já mostra a navegação desktop, coerente com o breakpoint do produto.

## Riscos residuais e pendências

- Escrita administrativa no SQLite pode adulterar/apagar dados ou causar negação de serviço; a aplicação fail-closed em leituras, mas não protege o host.
- Estado de sessão/grants permanece em memória e não deve ser interpretado como autenticação remota.
- A candidata aguarda auditoria independente e aceite humano de qualquer gate subsequente.
- Permanecem dois avisos de depreciação do Starlette/httpx nos testes da API e um aviso informativo do Next.js sobre a futura remoção de `next lint`; não bloquearam os gates.
- A chamada exploratória inicial `uv run --locked pytest -q` executada fora de `apps/api` terminou na coleta com incompatibilidade do ambiente global; a chamada repetida pelo runner oficial no diretório da API passou integralmente.

## Comandos e fechamento

- Runner RTK: `rtk printf 'R5 final verification stdout\n'` → stdout `R5 final verification stdout`, exit code `0`.
- API: `cd apps/api && uv run --locked pytest -q` → exit code `0`.
- Web: `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` → todos exit code `0`.
- Mobile: `npm test`, `npm run lint`, `npm run build` → todos exit code `0`.
- E2E: `npm run e2e -- --retries=0`, duas rodadas → exit code `0` em ambas.
- Portas locais: `rtk lsof -nP -iTCP:3000 -iTCP:8000 -sTCP:LISTEN` não encontrou processo; exit code `1` por ausência de resultados.
- Não houve merge, push, tag, deploy, conexão de contas reais, uso de dados pessoais nem instalação de serviço persistente.
