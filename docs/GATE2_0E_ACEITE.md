# JARVIS Gate 2.0-E — aceite formal

**Data:** 25/09/2026.  
**Decisão do proprietário:** aceite expresso do Gate 2.0-E somente local, sintético e de processo único; aceite das correções da Sprint Nightly aprovadas na auditoria independente; integração dos scaffolds macOS e Android como experimentais, sem aceite dos executáveis nativos.

## O que foi integrado

A branch `feat/gate2.0-e-integracao-formal` foi criada a partir de `main` em `fcca4eb5e5a002d4ddd2f0f33997e74e1c8a3c72` e avançou por fast-forward até o commit aprovado `ee5fc29220bbd594f5456ae51ed07f7e2e1fabd5` (árvore `b5b541ca87d68722f56c6ab8beb280006f043da9`). Não houve conflito. A `main` não foi movida. Não houve push, tag, deploy nem merge adicional.

Ancestrais conferidos dentro desse commit: baseline do Gate E `e648e92467396ce67b75019858fbcd0ee5557042` e Nightly `fbaca45446f31258e7a121b3a49284516fcc8243`.

O parecer independente foi copiado sem alteração para [GATE2_0E_PARECER_INDEPENDENTE.md](GATE2_0E_PARECER_INDEPENDENTE.md). SHA-256 do arquivo: `a346897ffaa0b426402af81d9a0e3263b5446b9d52219ef8c154a72a1bbd6ea2`.

Três arquivos não rastreados do checkout original foram preservados e não entram neste aceite:

| Arquivo | SHA-256 |
|---|---|
| `SUPERPROMPT_JARVIS_MADRUGADA_2026-09-25.md` | `8d16c2c0d70eb19e9bbbe7d458e9045344ec6a82f3845d7a4defb0262314d149` |
| `docs/ANALISE_PLAYLIST_JARVIS_2026-09.md` | `f9b6f9337b8da8eee2b5043ccac321f2ec519980701c66cf7cc0e16fb9132715` |
| `package-lock.json` na raiz | `928ea8e3b375c204f6307e85f190ac76074dddea2b79fefcda27fcd4ca61afeb` |

## Escopo aceito

- Interface web lendo a API local no modo real, com sessão, CSRF, concessão e Calendar simulado.
- DEMO e API em datasets separados. `domain_id` continua sendo classificação, não autorização.
- Correções Nightly: prova HMAC do runner E2E, validação de contexto, recuperação de Missões no `localStorage`, catálogo Calendar limitado por grant, linearização de leitura e revogação no mesmo processo, e remoção da permissão Tauri `opener:default`.
- Um único processo. Sessões e concessões permanecem voláteis.

## Experimental, sem aceite de executável

- `apps/desktop`: scaffold. O `npm run build` compila o frontend Vite. Tauri, `.app` e qualquer binário nativo não foram compilados nem aceitos.
- `apps/mobile`: scaffold. Testes de browser e o bundle Vite passaram. APK não foi gerado nem aceito.
- Missões e o ciclo de conhecimento continuam locais e sintéticos. A persistência de Missões é `localStorage`. O ciclo de conhecimento não está ligado à tela.

## Suíte desta integração

Executada na worktree `feat/gate2.0-e-integracao-formal` depois do fast-forward, ainda no commit `ee5fc29`, com dependências reinstaladas por `uv sync --locked --python 3.12` e `npm ci`.

| Comando | Resultado |
|---|---|
| `uv run --locked pytest -q` em `apps/api` | PASS — 149/149. Avisos conhecidos de Starlette/httpx e cookies do TestClient |
| `npx vitest run` em `apps/web` | PASS — 63/63 em 13 arquivos, incluindo o readiness HMAC |
| `npx tsc --noEmit` | PASS |
| `npx next lint` | PASS — sem erros nem avisos ESLint; o comando avisa que `next lint` será removido no Next 16 |
| `npm run build` em `apps/web` | PASS — Next.js 15.5.26 |
| `JARVIS_E2E_WEB_ORIGIN=http://127.0.0.1:3000 JARVIS_E2E_API_ORIGIN=http://127.0.0.1:8000 npm run e2e` | PASS — 36/36, exit 0. Runner oficial, banco temporário, prova HMAC da API filha |
| `npm test`, `npm run lint`, `npm run build` em `apps/mobile` | PASS — 2/2, Oxlint limpo, Vite |
| `PLAYWRIGHT_BROWSERS_PATH=/tmp/jarvis-pw-browsers npm run e2e` em `apps/mobile` | PASS — 4/4 no browser. Não é APK |
| `npm run build` em `apps/desktop` | PASS do bundle Vite. Não é binário Tauri |

Os três P2 foram revistos de novo e continuam abertos. O registro rastreável está em [GATE2_0E_BACKLOG.md](GATE2_0E_BACKLOG.md). Nenhum conector real foi autorizado para fechá-los.

## O que este aceite não faz

Não autoriza OAuth, conta real, Calendar Google, Gmail, Drive, LLM, API paga, listener público, hospedagem remota, múltiplos workers, dado pessoal ou institucional, nem escrita externa. Não declara o aplicativo de mesa nem o Android como funcionais.
