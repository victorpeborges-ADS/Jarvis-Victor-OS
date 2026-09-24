# Gate 1.3.2 — Handoff de acessibilidade

**Data:** 23/09/2026  
**Partida:** `feat/gate1.3.1-correcoes` @ `90c067c`  
**Branch:** `feat/gate1.3.2-a11y`  
**Objetivo:** drawer acessível, foco visível e contraste AA, sem Gate 2.

## Correções

- O drawer de proveniência abre em portal, recebe foco no fechar, contém Tab/Shift+Tab, fecha com Escape e restaura o acionador. Se o acionador sumir, o foco vai para `#conteudo`. O fundo fica `inert` e o scroll da página trava.
- `focus-visible:outline-none` e `focus:outline-none` saíram dos controles sem anel substituto. O anel global de 2px permanece.
- `ink-faint` passou de `#94a3b8` (2,50:1) para `#6a7380` (4,68:1 sobre o fundo, 4,59:1 sobre a superfície muted).

## Testes

| Suite | Resultado |
|-------|-----------|
| typecheck | PASS |
| lint | PASS |
| Vitest | **29/29 PASS** |
| Playwright desktop/mobile, build novo, porta 3013 | **24/24 PASS** |
| pytest | **10/10 PASS** |

Capturas em `docs/screenshots/a11y/`: drawer e foco, desktop e mobile.

## Riscos residuais

- Texto desabilitado usa opacidade 60% e pode ficar abaixo de 4,5:1. A WCAG isenta controle desabilitado.
- O anel de foco `#6366f1` passa de 3:1 como componente, não foi medido em todos os fundos.
- `TestClient` continua avisando a futura troca para `httpx2`.
- Gate 2 não foi iniciado.

## Encerramento

O aceite técnico do Gate 1 foi confirmado. Depois dele, o impacto da alternativa selecionada em Aprovações deixou de usar `#64748b` sobre o fundo real `#f8f8f9` (4,48:1) e passou a usar `#5c6a78` (5,22:1). O registro do encerramento está em `docs/GATE1_ENCERRAMENTO.md`.
