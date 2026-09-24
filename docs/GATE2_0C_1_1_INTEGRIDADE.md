# Gate 2.0-C.1.1 — Integridade da memória SQLite

## Escopo e baseline

Correção dos dois bloqueadores reproduzidos na auditoria do C.1: inicialização aceitava esquema incompleto apesar do histórico de migrações, e uma colisão de ID interno permitia substituir silenciosamente um evento de outra origem. Trabalho iniciado em `feat/gate2.0-c1-memoria` no commit auditado `da3435f4ef37468eb05fa03283f2d2324ea37ff3`, em árvore limpa; branch de correção: `fix/gate2.0-c1.1-integridade`.

Não foi usado nem inicializado o banco padrão. Os testes usam somente bancos temporários descartáveis e registros sintéticos. As migrações `0001` e `0002` foram preservadas; a regra nova é aditiva em `apps/api/migrations/0003_event_identity_and_provenance.sql`.

## Matriz dos achados

| Achado reproduzido | Resultado | Evidência da correção |
|---|---|---|
| `initialize()` aceitava banco migrado sem `audit_entries` | **PASS** | A inicialização compara o esquema efetivo com o esquema reconstruído pelas migrações antes de marcar o store pronto. Divergência gera `DatabaseCorruptError`; não há reparo automático. `apps/api/memory_store.py:93-110,146-224`. Regressão remove a tabela e confirma que ela continua ausente após a falha: `apps/api/test_memory_store.py:372-382`. |
| Ausência de índice obrigatório não era detectada | **PASS** | A comparação usa objetos SQL, `table_xinfo`, `index_list`/`index_xinfo` e `foreign_key_list`: `apps/api/memory_store.py:226-292`. A regressão remove `idx_audit_entries_occurred_at` e exige falha na inicialização: `apps/api/test_memory_store.py:385-391`. |
| Tipo de coluna incompatível podia passar pela inicialização | **PASS** | A assinatura de colunas inclui nome, tipo, nulabilidade, default, chave primária e coluna oculta; a definição SQL também compara restrições e triggers: `apps/api/memory_store.py:230-266`. A regressão troca `record_count` de `INTEGER` para `TEXT`: `apps/api/test_memory_store.py:394-406`. |
| Migração interrompida podia deixar DDL parcial | **PASS** | Cada migração continua transacional; falha provoca rollback antes do registro de versão (`apps/api/memory_store.py:167-187`). A regressão existente verifica que o DDL parcial e a versão não persistem: `apps/api/test_memory_store.py:153-168`. |
| Banco válido e migração anterior podiam ser rejeitados ou reaplicados | **PASS** | Inicialização vazia, reexecução idempotente, atualização v1→v2 e posterior avanço à v3 estão cobertos em `apps/api/test_memory_store.py:96-109,118-143`. |
| Mesmo ID interno de outra fonte substituía o evento anterior | **PASS** | A identidade é comparada antes de qualquer escrita; colisões lançam `EventIdentityConflict`. A prova consulta diretamente evento, proveniência e auditoria e confirma que título, domínio, source, referência e contagem de auditoria do original não mudaram: `apps/api/memory_store.py:354-427`; `apps/api/test_memory_store.py:409-442`. |
| Atualização legítima da mesma identidade deixava de ser idempotente | **PASS** | A identidade externa igual `(dataset, source_id, provider, resource_id, external_ref)` atualiza conteúdo e proveniência temporal mantendo o ID interno original. Regressão: `apps/api/test_memory_store.py:233-249`; concorrência básica: `apps/api/test_memory_store.py:480-502`. |
| Fixture DEMO poderia ser confundida com ID interno real | **PASS** | `EventRecord` aceita somente `real_evt_` com sufixo permitido e `dataset="real"`: `apps/api/memory_models.py:100-117`. O SQLite também impõe namespace e imutabilidade por triggers: `apps/api/migrations/0003_event_identity_and_provenance.sql:1-31`. Testes validam `evt_001` no modelo e no banco: `apps/api/test_memory_store.py:353-369`. |

## Contrato de identidade

- **ID interno:** estável, único e namespaced como `real_evt_<sufixo>`; não muda depois da criação.
- **Dataset:** entidades persistidas por este store continuam limitadas a `real`. Capturas DEMO permanecem no catálogo/rotas DEMO e usam seus IDs de fixture fora desta base.
- **Identidade de origem:** dataset + `source_id` + conector (`provider`) + recurso (`resource_id`) + `external_ref`.
- **Colisão:** ID interno existente com tupla externa diferente falha com `EventIdentityConflict`; o registro original permanece intacto. Se ID e referência apontarem para linhas diferentes, a operação também falha.
- **Idempotência permitida:** mesma tupla de origem/referência representa o mesmo evento. Conteúdo, classificação e timestamps/proveniência podem ser atualizados, preservando o ID interno original. Source, conector, recurso e referência externa não podem ser substituídos. Colisões são verificadas dentro de `BEGIN IMMEDIATE`; gravação do evento, proveniência e auditoria compartilham a mesma transação.
- Triggers impedem reutilização de namespace inválido e mutação direta da identidade/proveniência no SQLite. A aplicação ainda valida os modelos; os triggers são uma barreira de integridade adicional.

## Verificações executadas

Ambiente Python 3.12.14; dependências Python instaladas com `uv sync --locked`.

- `uv run --locked pytest -q`: **77 passed** (contagem após a última regressão de identidade SQL; Python 3.12.14).
- `npm test -- --run` em `apps/web`: **31 passed** em 6 arquivos. Nenhum arquivo de frontend foi alterado.
- `npm audit`: **0 vulnerabilidades**.
- `npm audit --omit=dev`: **0 vulnerabilidades**.
- `uv run --locked --with pip-audit pip-audit`: **No known vulnerabilities found** nas dependências Python efetivamente resolvidas. `pip-audit` foi ferramenta transitória de auditoria, não foi adicionada ao projeto/lockfile.
- `git diff --check`: sem erros de whitespace.

Avisos não bloqueantes observados: aviso de depreciação do `TestClient`/httpx do Starlette e aviso de cookies por requisição em um teste existente; o auditor também emitiu avisos de cache do CacheControl antes de concluir sem vulnerabilidades conhecidas.

## Riscos residuais e limites

- Divergência estrutural agora bloqueia a abertura; não há reconstrução automática nem recuperação de dados. Restauração confiável depende de backup e recuperação, fora do escopo deste incremento.
- O esquema esperado é derivado dos arquivos de migração locais e comparado com o banco; alteração maliciosa simultânea do código/migrações e do arquivo de banco não é uma fronteira de segurança contra o próprio usuário/processo local.
- O namespace distingue IDs internos reais dos IDs de fixture, mas não é autenticação nem autorização. Sessão, grants e autorização no servidor continuam sendo os controles de acesso; `domain_id` permanece classificação.
- Nenhuma conta, fonte externa, dado pessoal ou institucional, OAuth, backup, restauração ou integração foi introduzida.

## Próximo passo

Parar para auditoria independente do Gate 2.0-C.1.1. Este incremento não autoriza C.2, backup/restauração, OAuth, conectores reais, LLM ou acesso remoto.
