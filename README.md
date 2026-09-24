# JARVIS — Victor OS + Victor Context Hub

Gate 1 tecnicamente aceito em `gate1-accepted-v0.1`. Gate 2.0-B foi aceito e consolidado em `gate2-b-accepted-v0.1`. A branch `feat/gate2.0-c1-memoria` implementa a memória local C.1, ainda em auditoria.

> **Estado dos dados:** A interface Gate 1 continua usando exclusivamente fixtures DEMO. A API C.1 dispõe de armazenamento SQLite local separado, inicialmente vazio; registros sintéticos aparecem apenas em bancos temporários de teste. Não há integração com Google Calendar/Gmail/Drive nem importação de fixtures.

**Raiz:** `/Users/vic/Freela/Jarvis-Victor-OS`. Aceite técnico registrado a partir de `feat/gate1.3.2-a11y` @ `de1e26b`, com a correção pontual de contraste no cartão selecionado.

## Stack e estado técnico
- Frontend: Next.js **15.5.26** + React 19.1.1 + TypeScript 5.8.3 + Tailwind 3.4.17
- Backend: FastAPI **0.141.1** + Starlette **1.7.0** + Python **3.12**
- Testes versionados: Vitest 5.0.1 + Playwright 1.55.1 (`channel: chrome`, build novo na porta 3013) + pytest 9

A auditoria independente relatou, fora desta suíte versionada, 34 testes Vitest e uma passagem adicional de Playwright com axe. Esses testes não foram incorporados ao repositório.

## Como executar

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
# API: http://127.0.0.1:8000/docs; o banco vazio fica fora do repositório em Application Support/JARVIS.
# O runner suportado é serve.py; não inicie Uvicorn diretamente.
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
- `apps/api` — FastAPI local; sessão e concessões voláteis, SQLite separado das fixtures DEMO
- `docs/GATE2_0C_1_MEMORIA.md` — arquitetura, limites e verificações da memória C.1
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

Gate 1 permanece tecnicamente aceito. C.1 autoriza apenas a fundação SQLite local vazia e dados sintéticos em testes temporários. OAuth, fontes reais, backup cifrado, LLM, acesso remoto e deploy seguem fora do escopo e exigem nova autorização. Ver `docs/GATE2_0B_2_HARDENING.md`, `docs/GATE2_0C_1_MEMORIA.md` e `AGENTS.md`.
