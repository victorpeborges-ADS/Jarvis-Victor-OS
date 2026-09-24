# AGENTS.md — JARVIS (Victor OS + Victor Context Hub) · Gate 1

> Contrato canônico para todos os agentes (OpenCode, Codex, Cursor). Leia `JARVIS_Blueprint_v0.1.md` e `JARVIS_PromptPack_OpenCode_Codex_Cursor.md` antes de qualquer alteração.

## 1. Princípios não negociáveis
1. Fonte de verdade por domínio: Calendar/Gmail/Drive/GitHub/projetos são fontes; JARVIS indexa referências, não substitui.
2. Proveniência/recência: todo fato exibe origem, ID/URL, timestamp, última verificação, validade, confiança, escopo. Distinguir observação/inferência/proposta/decisão aprovada.
3. Humano no comando: consultar automaticamente em readonly; propor rascunhos; exigir confirmação explícita para envio externo, alteração de agenda, transferência, deploy ou ação financeira.
4. Separação de domínios: pessoal | empresarial/comercial | MedSyn | MCID com escopos distintos. Nunca copiar docs institucionais restritos ou dados sensíveis de saúde para banco pessoal sem autorização adequada.
5. Sem falsa autonomia: estados `mock | connected | stale | error | pending_approval` sempre visíveis. Nunca prometer background sem scheduler real.
6. Uma única arquitetura e backlog: este monorepo é a fonte; `AGENTS.md` é canônico.
7. Mobile-first e acessível: PT-BR, WCAG 2.2 AA, teclado/screen reader, claro/escuro, redução de movimento, estados de rede claros.
8. Proteger rotina real: automação não incentiva sobrecarga.

## 2. Arquitetura decidida (Gate 1)
- **Raiz:** `/Users/vic/Freela/Jarvis-Victor-OS` (não criar subdir `jarvis`). Preservar `JARVIS_Blueprint_v0.1.md` e `JARVIS_PromptPack_OpenCode_Codex_Cursor.md`.
- **Frontend:** `apps/web` — Next.js 15.5.26 + React 19.1 + TypeScript 5 + Tailwind CSS 3. App Router, PWA responsiva, animação frugal. Design system em `apps/web/components/ui` + `apps/web/app/globals.css` (tokens).
- **Backend:** `apps/api` — FastAPI + Uvicorn + Pydantic v2. Endpoints mock em Gate 1 (sem DB persistente); SQLite só se necessário. OpenAPI tipado em `/docs`.
- **Fixtures:** `fixtures/demo.json` — dados DEMO fictícios, sinalizados explicitamente. Única fonte de dados no Gate 1.
- **Infra Gate 1:** sem OAuth real, sem DB externo, sem n8n, sem LLM, sem túnel, sem deploy público. Tudo mock sinalizado.
- **Node:** global v26.7.0 (não LTS) compatível com Next.js 15.5.26 (>=18.17). Preferir LTS 22.x em produção futura via `.nvmrc` sem alterar global. Validado: `node --version` + `next --version`.
- **Python:** 3.12 fixado por `apps/api/.python-version` e `apps/api/uv.lock`; instalar com `uv sync --locked --python 3.12`. O runner oficial da API é `python serve.py` via `uv run`; não iniciar `main:app` diretamente pelo Uvicorn.

## 3. Estrutura
```
.
├── AGENTS.md
├── README.md
├── JARVIS_Blueprint_v0.1.md
├── JARVIS_PromptPack_OpenCode_Codex_Cursor.md
├── .gitignore
├── fixtures/demo.json
├── apps/
│   ├── web/   # Next.js
│   └── api/   # FastAPI
└── docs/      # handoff, decisões
```

## 4. Comandos reais (executar na raiz ou no app)
```bash
# Frontend
cd apps/web
npm install
npm run dev        # http://localhost:3000
npm run build
npm run lint
npm run typecheck  # tsc --noEmit
npm test           # vitest (se configurado)
npx playwright test
npx playwright test --project=mobile

# Backend
cd apps/api
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked pytest
uv run --locked python serve.py  # loopback; não executar uvicorn main:app
```

## 5. Política de dados e segurança (Gate 1)
- Apenas fixtures fictícias em `fixtures/demo.json`, marcadas `DEMO` na UI. Nenhum dado pessoal/institucional real no repo.
- Não acessar pastas irmãs (`../crivo_platform`, `../Medsyn`, etc.), credenciais, `.env`, chaves, tokens, cookies.
- Não configurar Google OAuth, provedores pagos, túneis, deploy público ou automações externas.
- Não commitar segredos. `.gitignore` bloqueia `.env`, `.venv`, `node_modules`, `.next`, `__pycache__`.
- Logs sem PII. Auditoria local apenas por nomes de variáveis quando necessário (Gate 2).

## 6. Gates de ações
- **Gate 1 (tecnicamente aceito):** somente mocks sinalizados. Nenhuma escrita externa. Tag `gate1-accepted-v0.1`. Aprovação humana continua obrigatória para qualquer ação que toque Google ou produção.
- **Gate 2 (não iniciado):** readonly Calendar/Gmail com OAuth menor privilégio, conta pessoal autorizada apenas. Escrita permanece DESATIVADA. Não começar sem nova autorização.
- **Gate 3+:** escrita só após testes de idempotência, concorrência, revogação e consentimento.

## 7. Convenções
- **Branches:** `feat/<gate>-<slug>` isolada; não alterar mesmos arquivos em worktrees simultâneas.
- **Commits:** convencionais (`feat:`, `fix:`, `docs:`, `chore:`), sem `git push` sem autorização.
- **Testes:** Playwright E2E desktop (1280x800) + mobile (390x844); unit com Vitest/Jest; backend com pytest; `lint` + `typecheck` + `build` devem passar.
- **Acessibilidade:** foco visível, navegação por teclado, `aria-*`, contraste AA, `prefers-reduced-motion`.
- **PT-BR:** toda UI e microcopy em português do Brasil.
- **Design:** premium sóbrio, hierarquia editorial, uma cor de ação, espaço em branco, animações funcionais. Nunca cockpit com 8 painéis.

## 8. Definition of Done (Gate 1)
- [x] 6 áreas navegáveis: Agora, Conversa JARVIS, Inbox, Domínios, Aprovações, Fontes/Privacidade
- [x] 3 jornadas E2E com fixtures coerentes e testes Playwright passando (desktop + mobile)
- [x] Design system + responsividade + estados loading/empty/error/stale/mock visíveis
- [x] Keyboard nav, foco visível, reduced motion, contraste AA
- [x] `npm run build` + `npm run typecheck` + `pytest` (se aplicável) verdes
- [x] Handoff com lista de arquivos, instruções de execução, screenshots, testes PASS/FAIL, limitações e próximo gate

## 9. Áreas proibidas
- Ler/escrever em `/Users/vic` além deste workspace; MCID, MedSyn, CRIVO, SOFF sem autorização explícita.
- `git reset --hard`, `git clean -fd`, `rm -rf`, instalação global, `npm install -g`, alteração do Node global.
- Deploy, túnel, exposição de porta pública, automação financeira, dados clínicos, wake word, Android Auto.

## 10. Handoff obrigatório
Responder com: BASELINE (branch/commit), OBJETIVO, ARQUIVOS ALTERADOS, DECISÕES, COMANDOS EXECUTADOS, TESTES PASS/FAIL/BLOCKED, CAPTURAS/DEMOS, RISCOS RESIDUAIS, PENDÊNCIAS DE AUTORIZAÇÃO, PRÓXIMO GATE.
