# Gate 1.3.1 — Handoff

**Data:** 23/09/2026  
**Partida:** `feat/gate1.3-estabilizacao` @ `004445f`  
**Branch:** `feat/gate1.3.1-correcoes`  
**Objetivo:** corrigir as falhas funcionais da auditoria independente. Drawer e contraste ficam para etapa separada.

## Correções

| Auditoria | Correção | Evidência |
|-----------|----------|-----------|
| `setItem` lança em quota/storage bloqueado e a UI anunciava sucesso | Leitura e escrita protegidas. Falha grava só em memória e a UI diz que a nota será perdida ao recarregar | `__tests__/resilience.test.ts`; E2E `quota não anuncia persistência` |
| Captura incompleta era aceita | JSON Schema `LocalCapture` exige id, domínio, tipo, título, status, data e evidência | rejeição em `readExtraCaptures` |
| `null` derrubava `recordsForDomain` | Entradas nulas, primitivas e sem `domain_id` são ignoradas | `domains.test.ts` |
| Extra com `inb_001` substituía a fixture | Capturas locais usam `local_<uuid>`. IDs canônicos têm precedência | teste de colisão |
| Duplicata já armazenada aparecia duas vezes | Deduplicação na leitura, teto de 50 | `resilience.test.ts` |
| Contrato só tinha um rótulo | `contracts/jarvis.demo.v1.schema.json`; Ajv no frontend; jsonschema + modelos Pydantic na API | `test_contract.py` e teste de schema no Vitest |
| Evento inválido derrubava a coleção da API | Itens inválidos entram em quarentena; JSON ilegível responde 422 | `test_invalid_event_is_quarantined` |

## Fronteira de autorização

`domain_id` classifica a memória. Não autentica nem autoriza leitura. A API Gate 1 continua mock, sem OAuth e sem fonte externa. Gate 2+ precisa impor autorização no servidor antes de qualquer dado real; o filtro da interface não substitui essa fronteira.

## Fora desta etapa

- Foco, Escape, Tab e restauração do drawer.
- Contraste de `ink-faint` (2,50:1).

## Testes

| Suite | Resultado |
|-------|-----------|
| typecheck | PASS |
| `next lint` | PASS |
| Vitest | **29/29 PASS** |
| Playwright desktop/mobile, build novo, `127.0.0.1:3013` | **20/20 PASS** |
| pytest Python 3.12 | **10/10 PASS** |
| `npm audit` | **0** |

## Riscos residuais

- Fallback em memória não sobrevive a recarregar; a interface declara isso.
- `TestClient` ainda avisa a migração futura para `httpx2`.
- `next lint` será removido no Next 16.
- Propostas e aprovações continuam como listas validadas só quanto ao tipo, sem o mesmo modelo estrito dos eventos.
