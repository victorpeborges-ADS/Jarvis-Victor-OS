# Gate 1.2 — Diagnóstico (pré-implementação)

**Baseline:** `estabilizacao/gate1.1` @ `0e348af`  
**Evidências:** `docs/screenshots/antes/` (cópia das capturas Gate 1.1)

| # | Problema | Evidência | Código |
|---|----------|-----------|--------|
| 1 | Nav inferior sobrepõe CTAs/conteúdo no mobile | `01-agora-mobile`, `03-inbox-mobile`, `04-dominios-mobile`, `05-aprovacoes-mobile` | `layout.tsx` `pb-20` insuficiente vs. nav + safe-area; `BottomNav` fixed |
| 2 | Agora: hierarquia densa; evidência sempre aberta; CTA timeline aponta Aprovações | `01-agora-mobile` | `page.tsx` painel EVIDÊNCIA inline; link “Ver linha do tempo” → `/aprovacoes` |
| 3 | Tempo: “Bom dia” fixo; “3 eventos” com 4 itens misturando e-mail; “EM 25 MIN” hardcoded | `01-agora-*` | `formatDate`/`Bom dia`; `events.slice(0,4)`; label fixo |
| 4 | Conectores “connected” parecem reais | `06-fontes-mobile`, Sidebar | `fontes/page.tsx`, `Sidebar.tsx` badge verde `connected` |
| 5 | Conversa: voz parece ativa; compositor rígido; starters genéricos | `02-conversa-mobile` | botão 🎙 sem `disabled`; input single-line |
| 6 | Inbox: pouco feedback pós-captura; hierarquia do CTA fraca | `03-inbox-mobile` | sem toast/banner; status EN `classified` |
| 7 | Domínios: chips cortados; scroll horizontal sem affordance | `04-dominios-mobile` | `overflow-auto` sem snap/máscara; E2E usa `force:true` |
| 8 | Aprovações: só Alt A acionável; IDs/idempotência na visão principal; horários mistos | `05-aprovacoes-mobile` | alternativas sem seleção; `idempotency_key` visível |
| 9 | Fontes: avisos stale repetidos; labels EN | `06-fontes-mobile` | stale no card + `StaleBanner`; `sync_status` cru |
| 10 | 404 padrão EN do Next.js | `07-erro-404-mobile` | sem `not-found.tsx` |

**Fora de escopo:** OAuth, LLM, Gate 2, alteração de contratos em `fixtures/demo.json` (só apresentação).
