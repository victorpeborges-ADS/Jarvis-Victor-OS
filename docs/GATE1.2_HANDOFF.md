# Gate 1.2 — Handoff UX / visual

**Data:** 23/09/2026  
**Baseline:** `estabilizacao/gate1.1` @ `0e348af`  
**Branch:** `feat/gate1.2-ux`  
**Objetivo:** Refinamento visual e de experiência das 6 áreas — sem alterar contratos de dados nem iniciar Gate 2.

## Diagnóstico
Ver `docs/GATE1.2_DIAGNOSTICO.md` (10 problemas com evidências em capturas + código).

## Decisões de UX
1. **Nav mobile:** variável `--bottom-nav-height` + `env(safe-area-inset-bottom)` no `main` e na `BottomNav`. Conteúdo e CTAs passam a reservar espaço (teste E2E de não-sobreposição).
2. **Agora:** hierarquia 5s — próximo / prioridade / alerta; evidência só sob demanda (drawer); timeline separa compromissos (3) e mensagens (2); relógio DEMO 09h00 + saudação coerente; “EM 30 MIN” derivado das fixtures.
3. **Conectores:** nunca “connected” cru — labels `simulado · ok` / `simulado · desatualizado` (âmbar), Sidebar + Fontes.
4. **Conversa:** starters curtos úteis; compositor textarea expansível; voz marcada como indisponível; disclaimer “sem LLM”.
5. **Inbox:** CTA “Classificar e salvar” em destaque; feedback pós-captura; estados vazios; status em PT-BR.
6. **Domínios:** chip-scroll com snap + padding; contexto ativo explícito; E2E sem `force:true`.
7. **Aprovações:** radio nas 2 alternativas; aprova a selecionada; rótulos rascunho local × alteração externa; detalhes técnicos recolhidos.
8. **Fontes:** um banner stale (só Drive); labels PT; proveniência preservada.
9. **404:** `app/not-found.tsx` em PT-BR com CTAs de recuperação.
10. **Paleta/tipografia:** preservadas (Inter + Newsreader, ink/paper).

## Arquivos alterados (principais)
- `apps/web/lib/demo.ts` — relógio DEMO, saudação, timeline helpers, labels
- `apps/web/app/layout.tsx`, `globals.css`, `BottomNav.tsx`
- `apps/web/app/page.tsx`, `conversa/`, `inbox/`, `dominios/`, `aprovacoes/`, `fontes/`
- `apps/web/app/not-found.tsx` (novo)
- `apps/web/components/ui/{primitives,Sidebar}.tsx`
- `apps/web/__tests__/*`, `e2e/journeys.spec.ts`, `scripts/capture.mjs`
- `docs/GATE1.2_DIAGNOSTICO.md`, `docs/screenshots/antes|depois/`

## Testes
| Suite | Resultado |
|-------|-----------|
| `npm run typecheck` | PASS |
| `npx next lint` | PASS (0 warnings) |
| `npm run build` | PASS Next 15.5.26 |
| `npm test` (vitest) | **15/15 PASS** |
| `npx playwright test` | **14/14 PASS** (7×2 viewports) |
| `pytest apps/api/test_main.py` | **4/4 PASS** |

Novas regressões: nav mobile sem overlap; seleção Alt A/B; coerência temporal; 404 PT; conectores sem `connected` cru; Domínios sem `force:true`.

## Capturas
- **Antes:** `docs/screenshots/antes/` (Gate 1.1)
- **Depois:** `docs/screenshots/depois/` (+ `*-mobile-viewport.png` para overlap real)
- Cópia canônica atualizada em `docs/screenshots/*.png`

## Jornadas (demo)
1. **Agora 5s** → próximo em 30 min → evidência no drawer → timeline compromissos/mensagens  
2. **Aprovações** → escolher Alt B → aprovar rascunho local → sem escrita externa  
3. **Inbox** → classificar e salvar → feedback → Domínios/CRIVO  

## Riscos residuais
- Relógio DEMO fixo (09h00) — saudação/relativos não acompanham o relógio do sistema (intencional Gate 1).
- Voz e LLM continuam placeholders honestos.
- `next lint` deprecated (Next 16).

## Pendências de autorização
Gate 2 (OAuth), deploy, dados reais — **proibidos**.

## Próximo gate
**Aguardar aprovação visual humana** com URL `http://localhost:3000` (`npm run build && npm run start`) e comparação `antes/` × `depois/`.
