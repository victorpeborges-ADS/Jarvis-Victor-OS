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

## Hardening D.1 — revogação, reconciliação e epoch

O D.1 fecha os achados da auditoria sem conectar serviços externos:

- **Revogação e commit:** `_grant_lock` coordena a leitura/revogação dos grants e o trecho que confirma cada página SQLite. O lock estabelece uma ordem serial: a revogação lineariza quando marca o grant revogado sob o lock; a página lineariza no commit SQLite enquanto mantém o mesmo lock. Se a revogação terminar primeiro, a página falha na validação e não grava nem avança cursor; se a transação entrar primeiro, a revogação aguarda sua conclusão. Páginas já confirmadas podem permanecer no banco, mas todas as leituras continuam exigindo grant ativo. O lock não cobre chamadas ao provider, paginação ou espera por rede. Após a sincronização, a rota valida novamente todo o escopo inicial antes de devolver contagens/estados. A decisão de resposta fica linearizada nessa validação; uma revogação posterior não pode retirar uma resposta que já esteja em serialização ou trânsito.
- **Escopo operacional do lock:** a coordenação é `RLock` em memória e pressupõe o runner local de processo único e grants voláteis. Não executar múltiplos workers/processos da API para compartilhar esta garantia.
- **CORS de classificação:** `PUT` foi incluído nos métodos CORS. O preflight só é aceito para origens locais explicitamente permitidas, método e cabeçalhos autorizados. A requisição efetiva continua sujeita a sessão, Origin, CSRF e grant de Calendar do domínio. Não há origem `*` com credenciais.
- **Snapshot completo:** a migração `0005_calendar_full_sync_reconciliation.sql` adiciona um identificador de snapshot e staging de referências vistas. Cada página atualiza eventos, proveniência, staging e cursor na mesma transação. Somente a página final confirma o snapshot e aplica cancelamento lógico aos eventos da mesma fonte/calendário ausentes do conjunto completo. A ausência numa sincronização incremental não cancela. Erro ou revogação não reconcilia; revogação descarta o staging e o cursor parcial. Falha recuperável mantém a página pendente até retomar; cursor inválido descarta a tentativa e inicia novo snapshot. Tombstones explícitos continuam sendo aplicados incrementalmente. Reaparecimento atualiza o mesmo ID externo estável e limpa `cancelled_at`.
- **Epoch do provider:** cada instância do simulador gera uma época aleatória independente por calendário; cursores contêm essa época. Um cursor de instância anterior recebe 410 simulado, é invalidado e dispara snapshot integral reconciliado. Isso detecta reinício; não tenta restaurar o estado volátil anterior do provider. Último sucesso permanece registrado e o estado segue `error`/`stale` até uma sincronização apropriada.
- **Eventos de dia inteiro:** continuam fora do modelo atual baseado em `datetime`. O tratamento de `date` inclusivo/exclusivo e fuso deve ser especificado e aprovado antes de qualquer integração real com Google Calendar.

### Evidência versionada do D.1

- `uv sync --locked --python 3.12`: PASS, Python 3.12.14.
- `uv run --locked pytest -q`: **136 passed**, dois avisos de depreciação conhecidos de Starlette TestClient/httpx e cookies. Inclui barreiras determinísticas para revogação, resposta HTTP e revogação no meio de snapshot; reconciliação após snapshot completo, ausência incremental, erro/retomada, cancelamento/reaparecimento e reinício real do provider.
- Teste de socket HTTP real: preflight `PUT` e classificação efetiva passaram em loopback; origem externa, método não autorizado e cabeçalho inesperado foram recusados.
- Frontend não teve arquivos de produção alterados; `npm ci` e Vitest: **31 passed** em seis arquivos. Build, typecheck, lint e Playwright não foram repetidos neste incremento de backend.
- `npm audit` e `npm audit --omit=dev`: **0 vulnerabilidades**. `pip-audit` sobre o export runtime do `uv.lock`: nenhuma vulnerabilidade conhecida.
- `git diff --check`: PASS. Testes da API usam bancos temporários; o banco padrão não foi inicializado.

O handoff e os limites do incremento estão em [`GATE2_0D_1_HARDENING.md`](GATE2_0D_1_HARDENING.md). Este trabalho não aceita/consolida o Gate D e não autoriza Gate E, OAuth, Google real, dados pessoais ou institucionais, deploy ou acesso remoto.
