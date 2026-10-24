# ADR-012 — Memória local, exportação e exclusões em backups

- Status: categorias sintéticas locais implementadas; restore isolado e ativação offline explícita com reconciliação de exclusões. Sem fluxo de ativação na UI ou autorização para banco diário.
- Data: 2026-10-22.
- Substitui: proposta de 2026-10-17.

## Escopo e armazenamento

A interface e a API trabalham com quatro categorias: captura explícita (`local_captures`), fato confirmado (`confirmed_facts`), evidência sintética (`external_evidence`) e proposta inferida (`inferred_proposals`). A API restringe proprietário, categoria e domínio pela sessão autorizada; `domain_id` classifica o registro, não concede acesso. Cada item mostra ID, categoria, domínio, conteúdo, origem (`source_kind`/`source_ref`), horários e revisão. Respostas do assistente não podem ser gravadas como fato confirmado.

O fluxo visível lista páginas sob demanda e permite abrir, criar, corrigir e excluir. Mutações exigem sessão/CSRF e revisão esperada. A UI não exporta ao abrir. O comando nativo de exportação percorre somente as categorias e domínios permitidos, até 5.000 registros, e serializa os itens ativos; não recebe um caminho do WebView. O seletor nativo escolhe o destino. O app exige `.json`, caminho canônico dentro de `Documents`, diretórios sem symlink e arquivo de destino regular sem symlink/hard link. Para destino existente há confirmação de sobrescrita. O arquivo é escrito com modo `0600` por temporário no mesmo diretório e publicado atomicamente. A exportação intencional é texto claro no destino escolhido; isso não é backup cifrado nem promessa de apagamento posterior.

O runtime usa o armazenamento descrito no ADR-013: o SQLite de trabalho fica em memória e o arquivo primário é um snapshot cifrado. Não há FTS nem cache independente de capturas: a busca consulta o banco aberto, seus índices SQLite são atualizados pela transação, e o estado da tela é memória transitória que é atualizada após exclusão. O código não mantém cache persistente de texto para purgar. Saídas previamente copiadas para registros de workflow/automação são dados independentes e não são apagadas pela exclusão da memória.

## Semântica de exclusão

“Excluir” remove a linha da instância atualmente aberta. A transação também grava/atualiza `memory_deletion_tombstones` (migração `0026_memory_deletion_tombstones.sql`) com categoria, ID, domínio, revisão excluída, instante, hash SHA-256 do conteúdo e ID determinístico da operação. O tombstone não armazena o corpo, mas o hash é derivado do corpo e pode permitir tentativa de adivinhação quando o conteúdo tem baixa entropia; ele não deve ser tratado como dado anônimo. A exclusão e o tombstone fazem commit na mesma transação. Capturas usam revisão (`0027_memory_capture_revisions.sql`); fatos, evidências e propostas já têm versão.

As regras são determinísticas:

- repetir a mesma exclusão na mesma revisão retorna a operação registrada sem inserir tombstone duplicado;
- uma revisão menor que a revisão excluída é conflito e não restaura nem altera a decisão;
- na mesma revisão, conteúdo cujo hash diverge é conflito explícito;
- no replay de restore, linha ausente permanece ausente; linha de revisão menor é removida; linha da mesma revisão precisa casar com o hash e então é removida; revisão estritamente maior é recusada no restore: o ledger atual não comprova a linhagem dessa revisão. Nenhum relógio decide que uma exclusão perdeu.

O tombstone é upsert por `(categoria, domínio, ID)`, mantendo a decisão mais nova. Não há código de expiração, coleta ou retenção limitada para tombstones: ficam no banco enquanto ele existir e são copiados em backups novos. Isso aumenta o tamanho do ledger ao longo do tempo. O código de backup também não expira nem apaga archives. Apagar uma linha não sanitiza backups `.jvb`, restores antigos, exports nem outros arquivos históricos. `secure_delete`/criptografia do primário não é garantia de wipe físico de SSD/APFS, snapshots ou cópias externas.

Capturas explícitas têm retenção operacional de no máximo 20 linhas abertas. Ao criar uma captura que ultrapasse esse limite, linhas mais antigas são removidas na mesma transação e recebem tombstone. A lista da interface e a resposta de busca são limitadas separadamente; esses limites de apresentação não expiram registros de outras categorias.

## Restore e backups legados

Backups criados agora contêm a tabela de tombstones no snapshot SQLite cifrado. Antes de publicar o restore isolado, a aplicação autentica o archive, valida/upgrada o snapshot em memória e reaplica os tombstones presentes nesse snapshot. Nenhuma busca, API ou UI usa esse banco antes desse passo; a publicação vai direto ao envelope cifrado do ADR-013. O restore **isolado**, sem um banco atual explícito, continua sem conhecer exclusões posteriores ao snapshot; um backup com ledger não vazio ainda pode recuperar esses itens nesse modo. Para substituir um banco atual, a biblioteca de ativação offline agora lê seu ledger sob leases exclusivas de manutenção e escritor e une as decisões ao snapshot restaurado, em memória e antes do staging/ativação. A chave `(categoria, domínio, ID estável)` identifica o item. Decisões iguais na mesma revisão são idempotentes; conteúdo/operação divergentes ou revisões de exclusão diferentes para a mesma identidade são recusados por falta de linhagem comprovada. A união fica no banco ativado e em backups futuros. Não há merge dos demais dados do banco atual.

Backup anterior ao ledger, ou sem tombstones, não prova que exclusões posteriores foram preservadas. O restore padrão falha com `LegacyDeletionConfirmationRequired` antes de criar o destino. Na interface de terminal, a opção `restore --confirm-legacy-resurrection` é a confirmação explícita e imprime aviso de que itens apagados podem voltar. A API Python exige `confirm_legacy_resurrection=True` para prosseguir. O archive antigo continua byte a byte intacto; o restore confirmado pode recuperar o texto antigo. Não se declara que archives ou restores antigos foram apagados ou sanitizados. O comando `restore` oferece restauração isolada. A biblioteca de ativação selada exige caminho explícito, chave em memória, plano e confirmação vinculada ao estado atual. O CLI `activate` continua sendo o adaptador legado sem transferência de chave selada; seu novo `--confirm-legacy-resurrection` explicita o mesmo aviso. Não há fluxo de restore/ativação na UI. Mesmo com ledger atual, a política conservadora exige confirmação se o backup não contém exclusões.

## Evidência registrada anteriormente

Ensaios usam bancos, dados e chaves sintéticos em diretórios `tmp_path` novos; nenhum banco diário é aberto ou migrado. Foram exercitados CRUD e origem/domínio, validação de campos extras, tombstone atômico e sem coluna de corpo, exclusão idempotente, conflito de revisão, busca após purga, exportação e validação nativa de caminho/symlink/colisão, restore de backup novo com replay, backup legado bloqueado até confirmação e permanência byte a byte do archive antigo com texto recuperável após confirmação. A integração da API passa pelo processo local supervisionado/UDS, incluindo os comandos de memória. Os testes TypeScript e Rust cobrem o contrato do IPC.

Comandos registrados na rodada anterior (não reexecutados como conjunto nesta subentrega):

- `cd apps/api && uv run --locked --offline pytest -q test_sealed_database.py test_memory_categories.py test_native_app_api.py test_native_runtime_process.py` — 78 aprovados; inclui upgrade/recuperação cifrados e um aviso de depreciação do TestClient/HTTPX.
- `cd apps/desktop/src-tauri && cargo test --offline --features mac003-production-supervisor-test` — 111 aprovados, 9 ignorados; inclui o supervisor/UDS real.
- `cd apps/desktop && node --test tests/runtimeCommand.test.mjs` — 19 aprovados.
- `cd apps/desktop && npx tsc --noEmit` — sem erros TypeScript.
- `git diff --check` — sem erros de whitespace.

O smoke visual não foi executado.

## Subentrega do fluxo de memória — 22/10/2026

Baseline: candidata `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, com modificados e untracked preservados. Foram reutilizados as quatro categorias, rotas, allowlists, limites e seletor nativo existentes, sem novas dependências ou comandos de produção.

Corrigidos dois defeitos reproduzidos: conflito ao excluir uma revisão desatualizada das três categorias retornava erro genérico por import ausente; capturas novas tinham `revised_at` vazio. A criação agora grava o instante inicial e a leitura admite capturas anteriores com esse campo vazio, usando `created_at`, sem migração de dados. As exclusões pelos dois fluxos da interface invalidam também as listas/detalhes correspondentes de memória e captura/busca; a invalidação de sessão limpa esses estados. O teste de interface é estrutural: não comprova comportamento visual nem todas as intercalações de respostas assíncronas.

### Formato de exportação existente

JSON UTF-8 com os únicos campos de raiz `format: "jarvis-local-memory-export"`, `schema_version: 1` e `records`. Cada registro contém exatamente `id`, `category`, `domain_id`, `body`, `source_kind`, `source_ref`, `version`, `recorded_at`, `revised_at`. Sessões, tokens, grants, chaves e configurações não integram esse esquema. Isso não é um detector de segredos eventualmente digitados no próprio conteúdo autorizado. A exportação não copia o arquivo do banco diário. Destino e escrita atômica são os descritos acima; o ensaio escolheu um caminho sintético sob um `Documents` temporário, sem abrir o seletor real ou a janela.

### Evidência desta subentrega

- Reprodução inicial: 4 failed, 68 passed; os quatro casos passaram após as correções. Não se atribui PASS à execução inicial.
- Node/IPC: `node --test tests/runtimeCommand.test.mjs tests/workflowHistory.test.mjs` — PASS, 28 testes, sem skips; inclui rejeição antes do IPC e regressão estrutural de invalidação.
- Rust/UDS: `cargo test --locked --offline --features mac003-production-supervisor-test --test mac003_production_supervisor` com target novo em `/tmp` — PASS, 1 teste, sem filtros. Exercita criação/correção/exclusão, conflito, origem, export autorizado, destino temporário escolhido e recusa após encerrar sessão.
- Rust/export: `cargo test --locked --offline --lib memory_export_tests` no mesmo target — PASS, 2 testes, 121 filtrados pelo módulo escolhido; valida esquema fechado e caminhos/symlink/colisão/escrita. Dois avisos de constantes não utilizadas no adaptador de armazenamento. Não é execução da suíte Rust completa; nenhum teste de Keychain foi executado.
- `cargo fmt --all -- --check` — PASS após formatar as adições ao harness.
- `./node_modules/.bin/tsc --noEmit` — PASS.
- Build via API local do Vite com `configFile:false`, `envDir:false`, plugin React existente e saída nova em `/tmp` — PASS. A primeira execução também passou, mas avisou sobre a depreciação de `envFile:false`; repetida com `envDir:false`, sem esse aviso. Nenhum arquivo `.env` foi carregado.

Os testes Python usam exclusivamente bancos temporários sintéticos. A matriz cobre CRUD nas quatro categorias, origem/domínio, revisão, campos extras, domínio inválido, sessão encerrada, busca após exclusão, replay efetivo de tombstones nas quatro categorias, restore legado com confirmação e ressurgimento de exclusão posterior ao snapshot como limitação explícita. `uv run --locked --offline --no-env-file pytest -q test_memory_categories.py test_native_app_api.py test_sealed_database.py test_backup_recovery.py test_restore_activation.py test_restore_activation_review.py test_native_runtime_process.py` — PASS, 254 testes, sem filtros/skips, 1 aviso de depreciação Starlette/TestClient, 170,50 s. A execução ampliada anterior passou com 249 testes antes das cinco novas verificações finais. `git diff --check` passou nos dois checkouts após as atualizações documentais.

Smoke visual e interação com o seletor nativo: NOT TESTED. Keychain, banco diário, provider real, OAuth, efeitos externos, APK e assinatura não foram exercitados. Nenhum backup histórico foi apagado ou sanitizado. Esta subentrega não constitui aceite para uso ou distribuição.

## Limites

- A exclusão cobre as tabelas da memória local, busca e estado de tela. Não remove texto copiado para resultados de workflows, exportações, backups, restores, snapshots do sistema ou outros arquivos.
- O tombstone guarda um hash do texto para detectar conflito por revisão; um atacante com acesso ao banco pode testar palpites de conteúdo provável.
- Tombstones não expiram e backups não têm política automática de expiração nesta implementação.
- Export é texto claro deliberado no caminho escolhido; se o processo cair durante gravação, um `.pending` pode sobrar no diretório permitido. O código limpa temporários nos erros observados de publicação, mas não promete limpeza após queda abrupta.
- Restore isolado reaplica somente as decisões do snapshot. A ativação offline sobre banco explícito reconcilia também o ledger atual. Banco diário não foi aberto ou ativado; cópias independentes, exports e saídas de workflows não entram nessa purga.
- Cópias transitórias em RAM e limitações do envelope estão descritas no ADR-013.

### Evidência da reconciliação — 22/10/2026

Baseline confirmado antes das alterações: `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, modificados e untracked preservados. Código alterado somente na candidata; nenhuma operação de stage/commit/merge/push/reset/clean. Leitura prévia: ADR-012, migrações 0021–0027, ledger, envelope, backup e ativação/recuperação existentes.

Comandos na candidata, `apps/api`, com Python 3.12 da `.venv` já instalada, sem instalar dependências, filtros, skips, retries ou sleeps:

```sh
.venv/bin/python -m pytest test_backup_recovery.py test_memory_categories.py test_restore_activation.py test_restore_activation_review.py test_sealed_database.py test_sealed_process_recovery.py test_memory_store.py -q --tb=short
.venv/bin/python -m pytest test_restore_deletion_reconciliation.py -q --tb=short
.venv/bin/python -m pytest test_native_runtime_process.py -q --tb=short
```

| Verificação final | Resultado |
| --- | --- |
| Sete módulos de regressão completos | PASS, 234 testes, 196,43 s; 1 aviso de depreciação Starlette/TestClient |
| Novo módulo de reconciliação completo | PASS, 93 testes, 160,87 s |
| Processo nativo completo, afetado pelo unlock | PASS, 4 testes, 6,59 s |
| `git diff --check` | PASS nos dois checkouts após documentação |

A nova matriz demonstra: captura presente no snapshot e excluída depois permanece ausente em lista, busca, abertura por ID/origem e descoberta de fontes; união de decisões exclusivas de cada lado e preservação em novo backup/restore; três demais categorias nos domínios A e B; invalidação de handle antigo; legado realmente anterior à migração 0026 recusado sem confirmação e ativado somente com confirmação; revisão concorrente/plano obsoleto, lease substituída, conflitos de revisão/conteúdo/operação e contenção de leases recusados; crashes por encerramento de processo nas 53 fronteiras do protocolo de ativação e em seis fronteiras da recuperação; falhas EIO/ENOSPC/EXDEV/EACCES e recusa de backup/unlock em runtime durante ativação pendente. Chaves sintéticas chegam aos filhos somente por pipe anônimo. As verificações de staging selado não encontram cabeçalho SQLite em claro nem o canário sintético. Fixtures legadas de regressão continuam sendo SQLite sintético explícito em diretórios temporários; a garantia de staging cifrado aplica-se ao destino selado, não transforma artefatos legados em envelopes.

Execuções anteriores **permanecem FAIL**, não são substituídas por um teste isolado:

- Primeira regressão de seis módulos, antes de adaptar consentimento: **117 failed / 75 passed**, 99,15 s; fixtures sem decisões não forneciam a confirmação agora obrigatória.
- Novo módulo inicial: **4 failed / 80 passed**, 136,04 s; leitura da fixture republicava o envelope com outro nonce entre a captura de bytes e a tentativa de restore. A captura passou a ocorrer após essa leitura; a asserção byte a byte foi mantida.
- Regressão ampliada: **4 failed / 230 passed**, 195,51 s; faltava consentimento no ensaio CLI e snapshots de alvo legado em WAL eram rejeitados pela nova desserialização. Corrigidos consentimento explícito e normalização em RAM dos marcadores de journal da cópia consistente.
- Nova matriz ampliada: **2 failed / 91 passed**, 141,72 s; migração de snapshot anterior ao ledger exigia `sqlite3.Row` e a fixture de runtime precisava configurar explicitamente seu caminho sintético. O migrador agora recebe linhas nomeadas e erros de migração viram erro de formato, sem publicação; a fixture exercita de fato o runtime com lease.
- Regressão intermediária: **1 failed / 233 passed**, 205,34 s; mesma deficiência de linhas nomeadas no ensaio de histórico adulterado. A execução final completa acima confirma a recusa após a correção, sem enfraquecer asserções.

As suítes finais abrangem nove módulos e 331 testes; não são a suíte API inteira. Nenhuma camada Rust/TypeScript ou allowlist foi alterada, portanto não foram reexecutadas nesta rodada. Banco diário, Keychain, .env, logs/argumentos de processos existentes, provider, OAuth, rede e efeitos externos ficaram fora. Smoke visual **NOT TESTED/BLOCKED**, janela não aberta; mobile **BLOCKED** por dependências ausentes, sem nova execução. APK e assinatura fora. Tombstones não expiram; archives/exports/cópias históricas não são apagados ou sanitizados. Não há garantia de recuperação automática com journal inicial ausente, artefatos corrompidos/ausentes ou software malicioso do mesmo usuário. Não há aceite para uso ou distribuição.
