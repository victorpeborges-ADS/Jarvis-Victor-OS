# Revisão de design e português

**Web:** mantida a linguagem editorial clara/escura e os tokens existentes em `apps/web/app/globals.css`. Header ajustado para 360 px; navegação mobile passou a cinco alvos legíveis (Agora, Inbox, Missões, Aprovar, Mais) com diálogo acessível para outras áreas. Inspeção visual manual das capturas `/missoes` 360 px e `/integrado` 390 px. Playwright capturou `/missoes` e `/integrado` em 360, 390, 768, 1024, 1440 e 1920 px e verificou ausência de overflow horizontal. `Mais` tem prova de teclado/Escape/foco em E2E.

**Fluxo de fonte:** nomes e estados em PT-BR, prévia local e SHA antes do envio, checkbox específico para dados fictícios, botão desativado até seleção/consentimento, estado pendente após envio, fila de artefatos e conhecimento separados. Mensagens de erro distinguem 401/403/409/422. O arquivo selecionado não some da fonte original.

**Nativos:** shell macOS e mobile usam rótulo visível `DEMO offline`, navegação e captura fictícia local; nenhuma tela promete API remota ou segundo plano. A interface do `.app` foi compilada e a primeira versão abriu; não houve inspeção automatizada de cada tela nativa. Mobile foi testado por navegador e E2E, sem aparelho/emulador Android.

**Acessibilidade:** foco visível, controles com labels, navegação teclado do diálogo, 44 px mínimo na bottom nav, `prefers-reduced-motion` preservado. Não foi feita auditoria WCAG 2.2 AA completa em todas as telas nem inspeção sistemática a zoom 200%; manter como pendência antes de aceite de produto.

**Glossário de estados:** `DEMO` = fixture/local fictício; `API local sintética` = FastAPI loopback e SQLite de teste; `Aguardando revisão` = ainda não autorizado para contexto; `Aprovado para contexto` = decisão humana separada; `BLOCKED` = etapa sem build/credencial. Termos técnicos necessários (SHA-256, API, SQLite) foram mantidos com contexto. Capturas e checksums em `EXPORTS_MANIFEST.json`.
