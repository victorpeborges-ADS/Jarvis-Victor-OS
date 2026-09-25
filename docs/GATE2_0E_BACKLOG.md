# Backlog aberto depois do Gate 2.0-E

Estas tarefas registram os três P2 confirmados na auditoria independente e de novo na integração de 25/09/2026. Nenhuma delas autoriza conector real, OAuth ou dado pessoal. O comportamento abaixo é o do Calendar simulado, em processo único.

## E-P2-1 — Estado do Calendar sem concessão

**Estado:** fechada em `feat/jarvis-g3-missoes-persistentes-p2`.
**Rota:** `GET /real/calendar-sim/state`.
**Contrato:** sem sessão, 401. Com sessão e sem grant de leitura `calendar:synthetic-primary`, 403. Com grant e nenhum calendário classificado no escopo, 200 e `states: []` — coleção autorizada vazia, não omissão de erro.
**Fora de escopo:** conectar Calendar real. OAuth e cloud continuam fechados.

## E-P2-2 — Metadado de calendário ainda não classificado

**Estado:** fechada em `feat/jarvis-g3-missoes-persistentes-p2`.
**Descoberta:** `GET /real/calendar-sim/calendars` lista calendário já classificado só no domínio da concessão de leitura. Nomes ainda não classificados aparecem apenas com o recurso separado `calendar:synthetic-inventory`, que não autoriza eventos nem sync.
**Classificação:** `PUT .../classification` de calendário sem domínio exige leitura do domínio alvo e inventário desse domínio. Calendário de outro domínio continua oculto e a classificação fora da concessão responde 403.
**Leitura de eventos:** continua no recurso `calendar:synthetic-primary`. Inventário não a substitui.
**Fora de escopo:** cliente Google e grant amplo por padrão. OAuth e cloud continuam fechados.

## E-P2-3 — GET autenticado sem Origin

**Estado:** fechada em `feat/jarvis-g3-missoes-persistentes-p2`.
**Política mínima:** `Origin` não autentica. GET loopback com sessão e grant pode omitir `Origin`, porque clientes locais e algumas navegações não o enviam. `Origin` fora da lista explícita responde 403. Mutação continua exigindo `Origin` permitido e CSRF. `Sec-Fetch-Site: cross-site` responde 403. `Host` não loopback responde 400. O bind segue só em loopback.
**Residual antes de dados reais:** ausência de `Origin` ainda não distingue um cliente local legítimo de um pedido forjado no mesmo host. Não abrir a API fora de `127.0.0.1`/`::1` com base nesta política.
**Fora de escopo:** hospedagem remota, túnel ou cookie em site público. OAuth e cloud continuam fechados.
