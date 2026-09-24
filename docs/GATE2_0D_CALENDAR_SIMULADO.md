# JARVIS Gate 2.0-D — Calendar simulado

## Escopo e limites

Este incremento entrega um fluxo local e inteiramente fictício para exercitar a ingestão até a memória SQLite. O provedor gera oito calendários e eventos sintéticos em memória. Não há cliente Google, OAuth, token de provedor, chamada HTTP, acesso à rede externa ou leitura das fixtures `DEMO`. A fonte persistida é `calendar_sim`, com recurso `calendar:synthetic-primary`; os eventos continuam no dataset `real`, sempre marcados nas respostas como `provider_mode: simulated`.

O processo local continua protegido pela sessão, CSRF, política de Origin e concessões voláteis existentes. A classificação `domain_id` não concede autorização. Cada operação de classificação exige uma concessão Calendar ativa para o domínio; a sincronização reconsulta as concessões antes de cada página e antes de gravá-la. A revogação bloqueia novas sincronizações e todas as leituras comuns/briefings pelas rotas já existentes.

## Contratos e persistência

`apps/api/calendar_simulator.py` contém contratos tipados para calendários, eventos do provedor, cursor, página, tombstones de exclusão, erros controlados, estado e relatório de sincronização. A normalização cria IDs internos estáveis no namespace `real_evt_cal_`, enquanto a proveniência mantém `source_id` e a referência externa composta por calendário e ID do evento. Fuso, início, fim, atualização do provedor e calendário ficam no payload minimizado do evento; a observação e a classificação humana ficam na proveniência.

A migração `0004_calendar_sync_state.sql` adiciona `cancelled_at` e checkpoints por calendário, com classificação, cursor opaco, estado e horários. O validador estrutural do C.1.2 verifica a migração junto ao restante do schema. Cada página grava eventos, tombstones de cancelamento, proveniência, auditoria minimizada e cursor dentro de uma transação. Checkpoints concorrentes usam comparação otimista; uma sincronização desatualizada relê o cursor. O evento cancelado é retido com proveniência, mas excluído de listagem, recuperação por ID e briefing.

Calendários sem classificação não têm seus eventos consultados nem persistidos. Calendários mapeados para domínio sem concessão ativa também não são consultados. O relatório da execução os identifica como `unclassified` ou `grant_missing`, sem incluir títulos ou conteúdo. A classificação é imutável neste incremento; uma correção de escopo futura requer fluxo explícito para evitar reinterpretar eventos já armazenados.

## Estados

- `provider_mode: simulated` acompanha todas as respostas; nenhuma resposta afirma conexão real.
- `not_synced` indica que ainda não houve sincronização concluída.
- `simulated` indica sincronização recente do provedor fictício.
- `stale` é calculado quando a última sincronização bem-sucedida tem 24 horas ou mais.
- `error` indica falha simulada mais recente que o último sucesso. O cursor e páginas já confirmadas são preservados para retomada.

Erro 410 simulado descarta apenas o cursor incompatível e refaz snapshot completo, mantendo a idempotência. Falhas simuladas de provedor não avançam o cursor da página falha.

## Rotas locais

Todas as rotas ficam sob `/real/calendar-sim` e exigem sessão válida. Alterações exigem Origin permitido e CSRF:

- `GET /calendars` — catálogo fictício sem eventos.
- `PUT /calendars/{calendar_id}/classification` — classificação humana explícita para domínio coberto por grant ativo.
- `POST /sync` — sincroniza todos os calendários classificados/autorizados ou um `calendar_id` informado.
- `GET /state` — retorna estados dos calendários mapeados e autorizados à sessão.

Exemplo de corpo da classificação: `{"domain_id":"dom_synthetic_a"}`. Exemplo de sincronização de um calendário: `{"calendar_id":"sim_calendar_a"}`. As rotas não adicionam credenciais nem criam grants automaticamente.

## Testes e reprodução

Execute na cópia de trabalho local, com Python 3.12. A suíte usa bancos temporários em `tmp_path`; não inicialize o banco padrão para reproduzi-la.

```bash
cd apps/api
uv sync --locked --python 3.12
uv run --locked pytest -q
```

O conjunto `test_calendar_simulator.py` cobre sessão, Origin/CSRF, separação DEMO/real, quarentena, autorização por domínio, paginação, idempotência, preservação de proveniência/fuso, cancelamento lógico, cursor 410, falha simulada, recuperação após reinício, revogação, concorrência, rollback e os oito domínios. Os testes existentes continuam verificando migrações, grants, sessões, CSRF, isolamento, backup e validação estrutural.

Resultado da implementação: **125 testes da API passaram** em Python 3.12 com `uv sync --locked`, e **31 testes Vitest passaram**. Nenhum arquivo de produção em `apps/web` foi alterado. Build, typecheck e lint do frontend não foram repetidos por não haver mudança no frontend; a revisão independente ainda deve reproduzir as verificações antes de qualquer consolidação.

## Riscos e fronteira do incremento

- Checkpoints e eventos persistem no banco local; sessões e grants continuam voláteis e precisam ser recriados após reinício.
- O provedor e suas alterações são voláteis em memória. Se uma sessão de paginação se perder, o erro 410 simulado aciona snapshot integral; o provedor não representa sincronização externa durável.
- Não há backup automático, criptografia do banco ativo, retenção automática, OAuth, revogação de token externo, conectores reais, LLM ou escrita externa.
- O catálogo incluído serve apenas para validar o fluxo sintético. Nenhum evento DEMO é copiado à memória SQLite.
- O Gate 2.0-D não autoriza OAuth, dados pessoais ou institucionais, nem o início do Gate E.
