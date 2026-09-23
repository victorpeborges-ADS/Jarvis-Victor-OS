# JARVIS — Victor OS + Victor Context Hub

Protótipo Gate 1.1 — estabilização com dados DEMO fictícios. Gate 2 continua proibido.

> **Aviso:** Todos os dados exibidos são fictícios e sinalizados como `DEMO` (badges, stale, proveniência). Nenhuma integração real com Google Calendar/Gmail/Drive ativa neste Gate.

**Raiz:** `/Users/vic/Freela/Jarvis-Victor-OS` (renomeada de `Jarvis:Victor OS` para remover `:` que quebrava `PATH`/`venv`/`Vite`). Branch: `estabilizacao/gate1.1` a partir de `6d44099`.

## Stack (Gate 1.1)
- Frontend: Next.js **15.5.26** (patch CVE-2025-66478 de 22/09/2026) + React 19.1.1 + TypeScript 5.8.3 + Tailwind 3.4.17
- Backend: FastAPI 0.110 + Python 3.14 (venv em `apps/api/.venv` agora funciona; pydantic-core requer 3.12 para build, ver Riscos)
- Testes: Vitest 3.2.7 + Playwright 1.55.1 (channel `chrome`) + pytest

## Como executar (sem cópias para /tmp)

### Frontend (apps/web)
```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000 (dev, requer build prévio para E2E)
npm run build      # produção
npm run start      # http://localhost:3000 (produção, usado por Playwright)
npm run lint
npm run typecheck  # tsc --noEmit (globals vitest)
npm test           # vitest run — 8 PASS direto na nova pasta
```

### Backend (apps/api)
```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # em Python 3.14 falha build pydantic-core (maturin) — usar Python 3.12 ou binary
uvicorn main:app --reload --port 8000  # http://localhost:8000/docs
pytest -q          # 4 PASS via global (venv pip BLOCKED em 3.14)
```

### Playwright (apps/web)
```bash
cd apps/web
# npx playwright install chromium  # timeout 300s diagnosticado — usar channel chrome existente
npx playwright test                # 10 PASS (5 cenários × desktop/mobile) via next start + channel chrome
npx playwright test --project=desktop
npx playwright test --project=mobile
```

### Capturas (6 telas × 2 viewports + estados)
```bash
cd apps/web
npm run build
node scripts/capture.mjs  # gera docs/screenshots/*.png via next start + chromium channel chrome
ls ../docs/screenshots
```

## Estrutura

- `apps/web` — Next.js 15 + React 19 + TypeScript + Tailwind
- `apps/api` — FastAPI (mock no Gate 1)
- `fixtures/demo.json` — dados DEMO
- `JARVIS_Blueprint_v0.1.md` — visão e arquitetura
- `JARVIS_PromptPack_OpenCode_Codex_Cursor.md` — prompts sequenciais
- `AGENTS.md` — contrato canônico

## 6 Áreas

Agora · Conversa JARVIS · Inbox · Domínios · Aprovações · Fontes/Privacidade

## 3 Jornadas Gate 1

1. Entender o dia em 5s (briefing com proveniência)
2. Resolver conflito sem alteração externa (proposta com 2 alternativas)
3. Capturar ideia e vincular a projeto (sem criar evento/e-mail)

## Gates

Gate 1 = mocks sinalizados. Gate 2 = readonly real (requer aprovação). Ver `AGENTS.md`.
