# Backlog aberto depois do Gate 2.0-E

Estas tarefas registram os três P2 confirmados na auditoria independente e de novo na integração de 25/09/2026. Nenhuma delas autoriza conector real, OAuth ou dado pessoal. O comportamento abaixo é o do Calendar simulado, em processo único.

## E-P2-1 — Estado do Calendar sem concessão

**Estado:** aberta.  
**Rota:** `GET /real/calendar-sim/state`.  
**Observado:** com sessão e sem grant, a resposta é HTTP 200 e `states: []`. No mesmo estado, `GET /real/calendar-sim/calendars` e `POST /real/calendar-sim/sync` respondem 403.  
**Pedido:** a ausência de concessão de Calendar deve falhar fechada também nesta rota, sem ampliar o que uma concessão permite ver.  
**Fora de escopo:** conectar Calendar real para “resolver” a rota.

## E-P2-2 — Metadado de calendário ainda não classificado

**Estado:** aberta.  
**Rota:** `GET /real/calendar-sim/calendars`.  
**Observado:** depois de classificar apenas `sim_calendar_a` em `dom_synthetic_a`, o catálogo devolve 8 calendários. Os não classificados aparecem como metadado de escolha. Classificar um domínio fora da concessão continua 403.  
**Pedido:** antes de qualquer lista de calendários reais, definir se o nome de um calendário não mapeado pode aparecer. No simulador, manter o contrato explícito até essa decisão.  
**Fora de escopo:** criar cliente Google ou alargar o grant para todos os domínios por padrão.

## E-P2-3 — GET autenticado sem Origin

**Estado:** aberta.  
**Rotas:** leituras `/real` que hoje aceitam ausência de `Origin`, em particular `GET /real/events`.  
**Observado:** com sessão e grant, a leitura sem `Origin` responde 200. `Origin` externo (`https://evil.example`) responde 403.  
**Pedido:** decidir, ainda no loopback, se a leitura autenticada exige `Origin` permitido. A decisão não deve abrir a API fora de `127.0.0.1`/`::1`.  
**Fora de escopo:** hospedagem remota, túnel ou cookie em site público.
