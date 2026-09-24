# JARVIS — Victor OS + Victor Context Hub

Gate 1 tecnicamente aceito em `gate1-accepted-v0.1`. O protótipo usa apenas dados DEMO. Gate 2 continua proibido.

> **Aviso:** Todos os dados exibidos são fictícios e sinalizados como `DEMO` (badges, stale, proveniência). Nenhuma integração real com Google Calendar/Gmail/Drive ativa neste Gate.

**Raiz:** `/Users/vic/Freela/Jarvis-Victor-OS`. Aceite técnico registrado a partir de `feat/gate1.3.2-a11y` @ `de1e26b`, com a correção pontual de contraste no cartão selecionado.

## Stack aceita no Gate 1
- Frontend: Next.js **15.5.26** + React 19.1.1 + TypeScript 5.8.3 + Tailwind 3.4.17
- Backend: FastAPI **0.141.1** + Starlette **1.7.0** + Python **3.12**
- Testes versionados: Vitest 5.0.1 + Playwright 1.55.1 (`channel: chrome`, build novo na porta 3013) + pytest 9

A auditoria independente relatou, fora desta suíte versionada, 34 testes Vitest e uma passagem adicional de Playwright com axe. Esses testes não foram incorporados ao repositório.

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
npm test           # vitest run
```

### Backend (apps/api)
```bash
cd apps/api
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked pytest -q
JARVIS_LOCAL_PASSPHRASE='defina-uma-frase-local' uv run --locked python serve.py
# API: http://127.0.0.1:8000/docs; não inicie com Uvicorn diretamente.
```

### Playwright (apps/web)
```bash
cd apps/web
# npx playwright install chromium  # timeout 300s diagnosticado — usar channel chrome existente
npx playwright test                # desktop e mobile, com build novo e servidor isolado
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

Gate 1 está tecnicamente aceito e permanece em mocks sinalizados. Gate 2, OAuth e qualquer fonte real continuam proibidos até nova autorização. Ver `docs/GATE1_ENCERRAMENTO.md` e `AGENTS.md`.
