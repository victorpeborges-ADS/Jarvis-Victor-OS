# GATE 1 — Handoff Protótipo Mock

**Data:** 23/09/2026  
**Branch:** main (git init local, sem push)  
**Commit:** a criar — `feat: gate1 prototipo navegavel com fixtures DEMO`  
**Objetivo:** Protótipo navegável mobile-first com 6 áreas e 3 jornadas E2E, dados DEMO fictícios, sem integrações reais.

## Baseline
- Raiz: `/Users/vic/Freela/Jarvis:Victor OS` (preservados `JARVIS_Blueprint_v0.1.md` e `JARVIS_PromptPack_OpenCode_Codex_Cursor.md`)
- Node global v26.7.0, Python 3.14.3, Next.js 15.3.5, React 19, Tailwind 3.4.17, FastAPI 0.110
- `.nvmrc` sugere 22.17.0 LTS para produção futura, sem alterar global (conforme AGENTS.md:2)

## Arquivos Alterados (Gate 1)
- `AGENTS.md` — contrato canônico
- `README.md` — instruções
- `.gitignore` + `.nvmrc`
- `fixtures/demo.json` — dados DEMO fictícios (única fonte Gate 1)
- `apps/web/*` — Next.js App Router, 6 páginas, design system, testes
- `apps/api/*` — FastAPI mock (7 endpoints), fixtures espelho

## Decisões
- Usar pasta atual como raiz, sem criar subdir `jarvis`
- SQLite não necessário no Gate 1 (fixtures JSON suficiente); mantido pronto para Gate 2
- Tailwind tokens custom (ink/paper/action/status) para estética premium sóbria, não dashboard genérico
- Proveniência visível por drawer, status `mock|connected|stale|error|pending_approval` sempre sinalizado
- TypeScript strict, ESLint, Playwright desktop 1280x800 + mobile 390x844, Vitest + jsdom

## Comandos Executados (reais)
```bash
# Verificação compatibilidade
node --version # v26.7.0
python3 --version # 3.14.3
# Frontend — workaround para ":" no caminho (PATH separator)
# npm scripts com ":" no path falham para tsc/vitest/venv; usar bin direto
./node_modules/.bin/tsc --noEmit      # apps/web
./node_modules/.bin/next build        # apps/web
./node_modules/.bin/next lint         # apps/web
# Vitest via cópia sem ":" (Vite não suporta ":" no path)
cp -R "apps/web" /tmp/jarvis-web/web && bash -c 'cd /tmp/jarvis-web/web && ./node_modules/.bin/vitest run'
# Backend
pytest # apps/api — 4 passed (via python global, venv com ":" falha, ver Riscos)
```

## Testes

### Frontend — Build/Lint/Typecheck
- `tsc --noEmit` (via bin direto) — **PASS**
- `next lint` — **PASS** (0 warnings)
- `next build` — **PASS** (9 rotas estáticas, sem viewport warnings após fix)

### Frontend — Vitest Unit (3 suites, 8 tests)
- Via `/tmp/jarvis-web/web` (workaround ":"), Vitest 3.0.9
- `__tests__/Agora.test.tsx` (4) — **PASS**
- `__tests__/Inbox.test.tsx` (2) — **PASS**
- `__tests__/Aprovacoes.test.tsx` (2) — **PASS**
- **Nota:** Em execução direta em `Jarvis:Victor OS` com ":", Vite falha em `Failed to load url /@vite/env` devido a ":" tratado como scheme. Workaround documentado.

### Backend — Pytest (apps/api)
- `test_health`, `test_briefing_has_next`, `test_events_demo`, `test_sources_stale_visible` — **PASS 4/4**
- **Nota:** `python -m venv .venv` recusa criar venv em path com ":" (`Refusing to create a venv ... PATH separator`). Testes rodaram via Python global com deps instaladas. Workaround: criar venv em `/tmp`.

### Playwright E2E (e2e/journeys.spec.ts — 5 cenários)
- **BLOCKED** — browsers não instalados (timeout em `playwright install --with-deps` na rede local). Configuração pronta para `desktop` + `mobile`, testes definem 3 jornadas + estados honestos + a11y.
- Para validar local: `bash -c 'cd /tmp/jarvis-web/web && ./node_modules/.bin/playwright test'` após `playwright install chromium`
- Manual smoke: `Agora` carrega próximo compromisso em <5s, `Aprovações` mostra diff com idempotency_key, `Inbox` captura sem criar evento externo — ver fixtures.

## Capturas / Demos
- Não geradas automaticamente devido a Playwright browsers pendentes e ":" no path.
- Screenshots esperados (desktop 1280 + mobile 390):
  - `Agora` — hero próximo compromisso + prioridade + alerta + timeline
  - `Conversa` — streaming mock + botão voz placeholder
  - `Inbox` — formulário captura + lista vinculada CRIVO
  - `Aprovações` — diff + 2 alternativas + botão aprovar (rascunho local)
  - `Fontes` — conectores mock/stale + proveniência
- Para gerar: `cd apps/web && ./node_modules/.bin/next dev` → `http://localhost:3000` (ou via `/tmp` cópia) e capturar com Playwright ou manual.

## Como Executar Localmente

### Frontend
```bash
cd "apps/web"
npm install
# Dev (workaround ":" — usar bin direto)
./node_modules/.bin/next dev        # http://localhost:3000
# Build / lint / typecheck (via bin direto devido a ":" no path)
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/next lint
./node_modules/.bin/next build
# Testes — vitest precisa path sem ":"
rm -rf /tmp/jarvis-web && mkdir -p /tmp/jarvis-web
cp -R "apps/web" /tmp/jarvis-web/web
bash -c 'cd /tmp/jarvis-web/web && ./node_modules/.bin/vitest run'
# Playwright (após instalar browsers)
bash -c 'cd /tmp/jarvis-web/web && ./node_modules/.bin/playwright install chromium && ./node_modules/.bin/playwright test'
# Ou direto (se browsers já instalados)
bash -c 'cd /tmp/jarvis-web/web && ./node_modules/.bin/playwright test --project=desktop'
```

### Backend
```bash
cd apps/api
# Workaround ":" — criar venv em /tmp
python3 -m venv /tmp/jarvis-venv && source /tmp/jarvis-venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000  # http://localhost:8000/docs
pytest -q
# Ou sem venv (global) se deps já instaladas
pytest
```

## Riscos Residuais
- **R1 — ":" no nome da pasta `Jarvis:Victor OS` quebra ferramentas que usam PATH como separador (`:`):** `npm run` PATH, `python -m venv`, `vite/vitest` (`/@vite/env`). Mitigação: usar bin direto (`./node_modules/.bin/...`) e cópia para `/tmp` para Vitest/Playwright/venv. **Recomendação:** renomear para `Jarvis-Victor-OS` ou `Jarvis_Victor_OS` (sem ":") para produção — requer aprovação.
- **R2 — Next 15.3.5 tem CVE (https://nextjs.org/blog/CVE-2025-66478):** build avisa vulnerabilidade. Atualizar para 15.5.x patch antes de Gate 2.
- **R3 — Pydantic-core não compila em Python 3.14 com maturin (Rust):** `pip install` falha para pydantic 2.11 em 3.14. Testes passaram via instalação global prévia, mas Gate 2 com DB exigirá pinagem `python 3.12` ou `pydantic` compatível. Fix: usar Python 3.12 LTS para backend ou aguardar pydantic com suporte 3.14.
- **R4 — Playwright browsers não instalados:** E2E BLOCKED até `playwright install`. Sem isso, 3 jornadas não têm evidência E2E automatizada, apenas unit + build.
- **R5 — Sem DB persistente Gate 1:** fixtures em JSON, sem testes de concorrência/idempotência reais — previsto para Gate 3.
- **R6 — Voz placeholder honesto:** sem STT/TTS real, conforme blueprint Gate 5 — não é bug.

## Pendências de Autorização
- Gate 2 readonly Calendar/Gmail OAuth — **NÃO INICIADO**, aguarda autorização para escopos mínimos em conta pessoal
- Renomear pasta para remover ":" — aguardar decisão
- Atualizar Next.js para versão patchada
- Instalar Playwright browsers e revalidar E2E desktop/mobile
- Definir Python LTS para backend (3.12 vs 3.14)

## Próximo Gate
**Gate 1 completo — aguardar aprovação visual/funcional antes de Gate 2.**  
Gate 2 só após: Codex review, threat model curto, OAuth readonly, adapters tipados, pipeline Event→proveniência→briefing, testes timezone `America/Sao_Paulo`, stale handling. Escrita permanece DESATIVADA.

## Checklist Definition of Done Gate 1
- [x] 6 áreas navegáveis (Agora, Conversa, Inbox, Domínios, Aprovações, Fontes) — rotas Next App Router
- [x] 3 jornadas com fixtures coerentes (daily 5s, conflito com 2 alternativas sem escrita, captura CRIVO sem criar reunião)
- [x] Design system premium sóbrio + responsivo + estados loading/empty/error/stale/mock visíveis
- [x] Keyboard nav, skip link, foco visível, `prefers-reduced-motion`, contraste AA (tokens)
- [x] `build` + `typecheck` + `lint` verdes (via workaround ":")
- [ ] Playwright E2E passando desktop+mobile — **BLOCKED** (browsers)
- [x] Handoff com instruções, testes, limitações, riscos, próximo gate
