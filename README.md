# JARVIS — Victor OS + Victor Context Hub

Gate 1 tecnicamente aceito em `gate1-accepted-v0.1`. Gate 2.0-B foi aceito em `gate2-b-accepted-v0.1`. Gate 2.0-C.1 foi tecnicamente aceito em `gate2-c1-accepted-v0.1`. Gate 2.0-C.2 foi tecnicamente aceito para backup cifrado e restauração isolada exclusivamente com bancos sintéticos, em `gate2-c2-accepted-v0.1`. Gate 2.0-D foi aceito exclusivamente para o adaptador Calendar simulado, em `gate2-d-accepted-v0.1` (código auditado `3175c0f`).

> **Estado dos dados:** A interface Gate 1 continua usando exclusivamente fixtures DEMO. A API C.1 dispõe de SQLite local separado; C.2 cobre backup/restauração de bancos sintéticos descartáveis; D cobre somente o provider Calendar simulado. Não há autorização para dados pessoais/institucionais, OAuth, Google Calendar real, Gmail, Drive ou importação de fixtures.

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

### Backup cifrado C.2 (somente ensaio sintético)

Após `uv sync --locked --python 3.12`, o CLI pede a senha diretamente no terminal; ela não deve ser passada por argumento ou variável de ambiente. Backup e restauração usam os caminhos padrão do banco, mas nunca inicializam o banco; restauração publica em diretório novo sob `restores/` e não substitui a base ativa. O aceite técnico está restrito a bancos sintéticos descartáveis. Consulte [docs/GATE2_0C_2_BACKUP_RECOVERY.md](docs/GATE2_0C_2_BACKUP_RECOVERY.md) e o [registro da auditoria independente](docs/GATE2_0C_2_ACEITE.md). Não há autorização para dados reais.

```bash
cd apps/api
uv run --locked python backup_cli.py backup
uv run --locked python backup_cli.py restore jarvis-backup-v1-20260924T120000Z-a1b2c3d4.jvb
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
- `docs/GATE2_0C_2_BACKUP_RECOVERY.md` — formato cifrado, execução e limites de backup/restauração C.2
- `docs/GATE2_0C_2_ACEITE.md` — decisão e evidências da auditoria independente C.2
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

Gate 1, Gate 2.0-B, Gate 2.0-C.1, Gate 2.0-C.2 e Gate 2.0-D estão tecnicamente aceitos, cada qual dentro do seu escopo. D cobre exclusivamente Calendar simulado e não autoriza dados pessoais/institucionais, OAuth ou Google real. A auditoria independente reportou 136 testes da API, 7 probes adversariais adicionais e 31 testes Vitest aprovados; esse resultado externo está documentado em `docs/GATE2_0D_ACEITE.md` e os probes externos não foram incorporados à suíte versionada. Riscos: coordenação de grants limitada a um processo; um GET decidido antes de revogação pode responder depois; eventos de dia inteiro não são suportados. A integração sintética da interface no Gate E está autorizada separadamente; não amplia a autorização para fontes ou dados reais.
