# JARVIS Gate 2.0-D.1 — Handoff de hardening

## Baseline e objetivo

- Branch criada: `fix/gate2.0-d1-calendar-hardening`.
- Base auditada: `feat/gate2.0-d-calendar-simulado` em `8a83e2af0e2bf10769f1d1bc28c7af9b613a63f1`.
- `main` de referência: `ccfcc3b14141030e65cd6e660bc13869e95b9b74`; permaneceu inalterada.
- Commit de implementação: `992f5f5735aeaff71a85ab2f39890465323c6055` (`fix: harden simulated calendar sync`).
- Objetivo: corrigir coordenação de revogação, CORS PUT, reconciliação de snapshots completos e cursores após reinício do provider simulado.

O banco padrão não foi aberto nem inicializado. Os testes utilizaram `tmp_path`/arquivos SQLite descartáveis; a execução final também apontou `JARVIS_DATABASE_PATH` para `/tmp/jarvis-d1-test-guard/memory.sqlite3`. Nenhuma conta ou serviço externo foi acessado.

## Decisões e comportamento

### Revogação e ponto de linearização

`local_security.py` usa um `RLock` compartilhado por leituras/mutações de grants, revogação e `calendar_grant_guard`. O serviço chama o provider antes de adquirir esse lock. Para gravar uma página, adquire o guard, valida de novo o domínio e mantém o guard somente ao redor da transação SQLite que grava eventos, proveniência, cancelamentos, staging, auditoria minimizada e cursor. O lock estabelece ordem serial; a revogação lineariza ao marcar o grant como revogado sob o lock, e a página ao confirmar sua transação SQLite sob o mesmo lock.

- Se a revogação lineariza antes do commit da página, a validação falha; a página não grava e o cursor não avança. Um snapshot incompleto é descartado.
- Se a página confirma primeiro, a revogação aguarda o fim da seção crítica. Dados confirmados permanecem armazenados, mas não podem ser lidos sem grant.
- Antes de responder, a rota sincroniza revalida o escopo autorizado inicial sob o mesmo guard. Uma revogação concluída antes dessa decisão recebe 403 e não retorna contagens nem estado do domínio.
- A linearização da resposta é a validação final. Uma revogação que ocorra depois dela não pode retirar bytes já serializados ou enviados.
- O lock é local ao processo e os grants seguem voláteis. A garantia requer um único processo/worker da API, conforme o runner local. `RLock` não coordena processos independentes.

### CORS e classificação

`PUT` passou a integrar os métodos CORS permitidos. Os testes usam HTTP/socket real em `127.0.0.1`; preflight válido para `PUT` e `content-type,x-csrf-token` passa. Origem externa, `PATCH` e cabeçalho adicional são recusados. O `PUT` efetivo exige sessão, Origin permitido, CSRF e grant ativo para o domínio. `allow_credentials` permanece habilitado apenas com origens locais explícitas; wildcard não é usado.

### Ausência em ressincronização

A migração `0005_calendar_full_sync_reconciliation.sql` adiciona `full_sync_id` ao checkpoint e tabela staging `calendar_sync_seen_events`. Todas as páginas do snapshot registram suas referências vistas. A reconciliação ocorre atomicamente, apenas quando a última página confirma um `next_sync_token`:

- eventos ausentes no snapshot completo recebem `cancelled_at`; linhas e proveniência permanecem preservadas;
- ausência numa sincronização incremental não significa exclusão;
- snapshot parcial, erro do provider ou revogação não executa reconciliação;
- a revogação limpa staging/cursor incompleto; falha recuperável não conclui o snapshot;
- tombstone explícito é aplicado como cancelamento lógico;
- evento reaparecido atualiza a identidade existente e remove o cancelamento.

### Epoch do provider

Cada instância do provider gera uma época aleatória por calendário, incorporada aos cursores. O estado do simulador não é restaurado após reinício. A instância nova recusa cursores antigos com 410; o serviço limpa cursores/staging e exige novo snapshot completo, reconciliando eventos que não voltaram. Uma época incompatível nunca é aceita silenciosamente. Erro/stale continuam associados ao último sucesso até um novo snapshot terminar.

## Arquivos alterados

- `apps/api/local_security.py`, `calendar_sim_api.py`, `calendar_simulator.py`, `main.py`.
- `apps/api/memory_models.py`, `memory_store.py`, nova migração `migrations/0005_calendar_full_sync_reconciliation.sql`.
- `apps/api/test_calendar_simulator.py`, `test_memory_store.py`.
- `docs/GATE2_0D_CALENDAR_SIMULADO.md`.

Nenhum arquivo de produção do frontend foi alterado. Eventos de dia inteiro continuam fora do contrato: definir regras para datas inclusivas/exclusivas e fuso é requisito pendente antes do Google Calendar real.

## Testes e verificações

| Verificação | Resultado |
|---|---|
| `uv sync --locked --python 3.12` | PASS — Python 3.12.14, lock resolvido e dependências verificadas. |
| `uv run --locked pytest -q` | PASS — **136 testes**, execução final com caminho de salvaguarda em `/tmp`; 2 avisos de depreciação não bloqueantes. |
| Regressões determinísticas de grants | PASS — barreiras demonstram revogação antes do commit e revogação entre commit e decisão HTTP; revogação no meio do snapshot não reconcilia nem avança cursor parcial. |
| Reconciliação e cursor | PASS — snapshot completo cancela ausente; incremental não infere exclusão; falha não cancela; retry conclui; reaparecimento reativa; provider recriado rejeita epoch antigo e ressincroniza. |
| CORS em socket HTTP real | PASS — preflight PUT e classificação real em loopback; origem externa/método/header não permitido recusados. |
| `npm ci` / Vitest | PASS — instalação limpa; **31 testes em 6 arquivos**. |
| `npm audit` / `npm audit --omit=dev` | PASS — zero vulnerabilidades. |
| `pip-audit` no export runtime do lock | PASS — nenhuma vulnerabilidade conhecida; scanner não foi adicionado ao ambiente/lock da aplicação. |
| `git diff --check` | PASS. |
| Build, typecheck, lint e Playwright | Não repetidos: nenhuma alteração frontend de produção. |

Avisos do pytest: depreciação de integração httpx do Starlette TestClient e de cookies por requisição em um teste preexistente. Não alteram o resultado.

## Limites e riscos residuais

- A coordenação de grants é em memória e de processo único; não protege topologias com múltiplos workers. Grants também não sobrevivem ao reinício.
- Uma revogação posterior à decisão final da resposta não consegue recolher uma resposta já serializada/enviada. Registros confirmados antes da revogação permanecem no SQLite, mas consultas subsequentes continuam autorizadas no servidor.
- Falhas de provider podem deixar eventos de páginas anteriormente confirmadas no banco; não há reconciliação até snapshot completo. Em cursor 410, a ressincronização completa define o conjunto corrente.
- Eventos de dia inteiro não são representados corretamente pelo contrato atual; bloquear a integração real até decisão específica.
- Não foram adicionados OAuth, cliente Google, acesso externo, integração de UI, LLM, dados pessoais/institucionais, deploy, backup adicional ou Gate E.

## Próximo passo

Parar para auditoria independente do Gate 2.0-D.1. Não fazer merge, push, deploy, conexão real com Google nem iniciar o Gate E antes de nova autorização.
