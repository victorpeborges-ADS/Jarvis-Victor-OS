# Gate 1.3 — Handoff de estabilização

**Data:** 23/09/2026  
**Partida:** `feat/gate1.2-ux` @ `957fe60`  
**Branch:** `feat/gate1.3-estabilizacao`  
**Objetivo:** correção funcional antes de integração real. Sem Gate 2.

## Defeitos reproduzidos (evidência) e correção

| ID | Defeito | Evidência antes | Correção | Teste |
|----|---------|-----------------|----------|-------|
| F1 | Filtro de domínio por título, palavra e sensibilidade | `dominios/page.tsx` (`title.includes("MedSyn")`, `title.includes("crivo")`, `sensitivity === "internal"`) | `domain_id` explícito em `lib/domains.ts` | vitest isolamento + E2E dos 8 domínios |
| F2 | Inbox e Domínios não compartilhavam estado; captura sumia na navegação | `useState(fixtures.inbox)` só na página | `lib/demo-inbox-store.ts` (`localStorage`, teto 50, só DEMO) | E2E com `trace-*` + reload |
| F3 | Três cópias de fixture | `fixtures/demo.json`, `apps/web/fixtures/demo.json`, `apps/api/demo.json` | Só `fixtures/demo.json`; API sem fallback | pytest lê o canônico |
| F4 | Seletores frágeis e `force:true` no histórico E2E | `span:has-text("CRIVO")`, scroll forçado | `data-testid` + abas quebrando linha (clique real) | Playwright sem `force` |
| F5 | PostCSS aninhado e Vitest vulneráveis | `npm audit`: postcss `<=8.5.22` high; vitest moderate, correção só em 5.x / Next 16 | override `postcss@8.5.28` (também no Next 15.5.26); `vitest@5.0.1`. Sem `--force` | `npm audit`: 0 |
| F6 | API sem ambiente 3.12; FastAPI/Starlette antigos | `requirements.txt` fastapi `0.110.3`; Python global 3.14 | `.python-version` 3.12; venv via `uv`; fastapi `0.141.1`, starlette `1.7.0`, pytest `9.0.3` | pytest 5 PASS; `pip-audit` limpo |

## Decisões
- Domínio, confidencialidade (`sensitivity`) e proveniência são campos distintos. Título não classifica.
- `domain_id` desconhecido ou nulo não lança: fica em “Fora dos 8 domínios” e não entra em nenhum filtro. Sem cópia automática entre domínios.
- Evento `evt_006` é MedSyn e cita CRIVO só no título.
- Capturas extras vivem só no `localStorage` do navegador. Limites escritos na UI. Fixtures continuam a base.
- E2E sobe build novo em `127.0.0.1:3013` com `reuseExistingServer: false`.
- Abas de domínio em `flex-wrap` para o alvo de toque não ficar clipado no scroll horizontal.

## Arquivos principais
- `fixtures/demo.json` — esquema `jarvis.demo.v1` + `domain_id`
- `apps/web/lib/domains.ts`, `apps/web/lib/demo-inbox-store.ts`, `apps/web/lib/demo.ts`
- `apps/web/app/dominios/page.tsx`, `apps/web/app/inbox/page.tsx`
- `apps/web/e2e/isolation.spec.ts`, `apps/web/playwright.config.ts`
- `apps/web/__tests__/domains.test.ts`
- `apps/api/main.py`, `apps/api/requirements.txt`, `apps/api/.python-version`
- removidos `apps/web/fixtures/demo.json` e `apps/api/demo.json`

## Testes
| Suite | Resultado |
|-------|-----------|
| `npm run typecheck` | PASS |
| `npx next lint` | PASS |
| `npm test` (vitest 5.0.1) | **20/20 PASS** |
| `npm run build` (dentro do webServer E2E) | PASS |
| Playwright desktop+mobile, porta 3013, build isolado | **18/18 PASS** |
| `apps/api/.venv` Python 3.12.14 `pytest` | **5/5 PASS** |
| `npm audit` | **0 vulnerabilidades** |
| `pip-audit` | **No known vulnerabilities** |

## Riscos ainda abertos
- Aviso `StarletteDeprecationWarning`: `TestClient` via httpx; Starlette sugere `httpx2`. Não é CVE. Escrita real continua desligada.
- `next lint` será removido no Next 16. Next permanece 15.5.26.
- Persistência DEMO é local ao navegador; não é backup nem sincronização.
- Gate 2 (OAuth, Gmail, Calendar, LLM, deploy) não iniciado.

## Como repetir o ambiente Python
```bash
cd apps/api
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/pytest -q
```

## Parada
Aguardando revisão independente. Nenhuma integração real foi ligada.
