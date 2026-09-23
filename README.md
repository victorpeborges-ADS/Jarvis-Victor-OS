# JARVIS — Victor OS + Victor Context Hub

Protótipo Gate 1 — interface navegável com dados DEMO fictícios.

> **Aviso:** Todos os dados exibidos são fictícios e sinalizados como `DEMO`. Nenhuma integração real com Google Calendar/Gmail/Drive ativa neste Gate.

## Como executar

### Frontend (apps/web)
```bash
cd apps/web
npm install
npm run dev    # http://localhost:3000
npm run build
npm run lint
npm run typecheck
```

### Backend (apps/api)
```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000  # http://localhost:8000/docs
pytest
```

### Playwright
```bash
cd apps/web
npx playwright install
npx playwright test
npx playwright test --project=mobile
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
