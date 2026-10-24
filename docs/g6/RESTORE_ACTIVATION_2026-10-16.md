# DEC-08 — Aprovação limitada e bloqueio de implementação

> Atualização de 22/10/2026: a seção «Reconciliação de exclusões posteriores ao backup» ao final substitui os limites históricos de ativação somente SQLite legado. A biblioteca agora aceita snapshot selado com chave explícita em memória. O CLI sem transferência de chave continua legado. Não há ativação pela UI nem ensaio no banco diário.


## Baseline e objetivo

Worktree `/Users/vic/.codex/worktrees/jarvis-integration-candidate/Jarvis-Victor-OS`; branch `codex/jarvis-integration-candidate`; HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`; `main` `21f1537e14706a42e8272f92cb4f4b6dab746640`. Estado inicial conferido: **15 modificados e 6 untracked**, nada staged. Um inventário de hash/tamanho dos 21 arquivos locais e do documento C.2 foi registrado antes de editar.

Pedido: implementar ativação offline com staging/rollback/registro durável e schema exatamente compatível. A instrução aprova essa opção, exige somente testes sintéticos temporários e determina parar se houver decisão adicional. **Resultado desta rodada: aprovação limitada registrada; implementação BLOCKED em DEC-08-A, sem código de ativação.**

## Leituras e evidência do bloqueio

Foram lidos `AGENTS.md` e os documentos canônicos do projeto (também lidos nas rodadas anteriores), `DECISIONS_PENDING.md`, C.2, o código atual de `backup_cli.py`, `backup_recovery.py`, resolução/conexões em `memory_store.py`, lifespans de `main.py`, `serve.py`, launcher e scheduler. O contrato atual aceita apenas backup com o manifest de migrations completo e checksums atuais; não foi ampliado para schema antigo.

O requisito do passo 2 do DEC-08 é mais forte que adicionar um arquivo com flock: exige exclusão de leitores/writers e recusa de versão antiga sem adesão. Os runtimes atuais não mantêm lease de processo, e as conexões de `SQLiteMemoryStore.transaction()` são fechadas a cada operação. Um runtime antigo sem conexão aberta naquele instante não é excluído por um teste de busy/lock do SQLite. Uma lease do código novo também não é observada automaticamente por um processo antigo.

**Probe sintético executado:** subprocesso Python com o `SQLiteMemoryStore` atual inicializa um banco novo em diretório temporário privado, sinaliza `ready`, aguarda stdin e grava `record_audit("memory_read", 1)`. Enquanto ele aguarda, o processo controlador cria um arquivo privado de manutenção e adquire `flock(LOCK_EX|LOCK_NB)`. O filho recebe `go`, confirma `write_succeeded` e termina cooperativamente com exit 0. Resultado observado: **a escrita ainda é permitida pelo código anterior ao novo protocolo**. Não foi iniciado o app, runner, listener ou UI, nem executada ativação. O probe não alega ter implementado ou testado a barreira futura.

- Comando: `rtk env UV_OFFLINE=1 uv run --locked --offline --python 3.12 python -c <probe em memória com subprocesso, flock e caminho explícito>` em `apps/api`.
- Diretório criado exclusivamente para esse probe: `/var/folders/q6/3c9fm74977l7425bpd0195100000gn/T/jarvis-dec08-lease-probe-sl1sb7rt`.
- Banco exclusivamente sintético: subdiretório `private/memory.sqlite3`. Nenhum default de banco foi usado.
- O processo sintético concluiu por stdin/exit normal; nenhum processo do usuário foi interrompido. O diretório temporário foi preservado.

## Decisão pendente e limite da autorização

Aprovação registrada em DEC-08: opção offline, schema exato, validação integral, barreira, WAL/sidecars corretos, rollback independente, registro recuperável, caminhos/espaço/integridade, confirmação no produto e nenhuma exclusão automática de backup/rollback. Não aprova executar ativação real nesta sessão nem upgrades/backup com schema antigo.

Falta escolher a política de admissão do banco ativo no protocolo novo:

- Proposta recomendada, ainda não aprovada: primeira entrega somente para bancos criados sob o novo protocolo; bancos preexistentes ficam recusados para ativação até decisão própria de adoção.
- Alternativa, também não aprovada: adoção offline de banco existente com declaração explícita de encerramento das versões antigas, reconhecendo a limitação de não haver prova automática contra software que ignore as leases.

Isso não altera o critério de schema dos backups. A pergunta foi apresentada ao proprietário; nenhuma opção foi presumida. Não se usou PID/lsof/marcador recém-criado como substituto de uma política de transição aprovada. Nenhum mecanismo parcial de troca ficou exposto no produto enquanto essa decisão está pendente.

## Arquivos alterados e preservação

- `docs/g6/DECISIONS_PENDING.md`: adendo de aprovação limitada e DEC-08-A; conteúdo anterior preservado.
- `docs/GATE2_0C_2_BACKUP_RECOVERY.md`: adendo que distingue autorização futura e capacidade não implementada.
- Este handoff novo.

Nenhum arquivo de produção/teste existente foi alterado nesta rodada. Sem migrations, dependências, mudanças de autenticação, allowlists, UDS, PID, HMAC, CTR, replay ou separação capability/sessão/grant. Nenhum backup ou rollback do usuário foi aberto ou excluído.

## Comandos e verificações

| Verificação | Resultado |
|---|---|
| `rtk git status --short --branch`; `rtk git rev-parse HEAD main` | PASS: baseline e estado inicial conferidos |
| Leituras/buscas locais com `rtk cat`, `rtk sed`, `rtk rg`; inventário SHA-256 | PASS: código e documentos inspecionados sem selecionar banco diário |
| Probe sintético em subprocesso descrito acima | PASS como demonstração da lacuna atual; não é teste de ativação nem prova de segurança futura |
| `rtk env UV_OFFLINE=1 JARVIS_DATABASE_PATH=/tmp/jarvis-dec08-unused-default-20261016/memory.sqlite3 uv run --locked --offline --python 3.12 pytest -q test_backup_recovery.py` em `apps/api` | PASS: **25 testes**, bancos temporários sintéticos; backup/restore isolado existente preservado |
| Sucesso/incompatibilidade/corrupção/concorrência/ENOSPC/crash/recovery da ativação | BLOCKED / não implementados; não contar os 25 testes C.2 como cobertura da ativação |
| Build Rust/frontend | Não necessário: nenhuma alteração Rust/frontend; nenhum build novo |
| Preservação dos arquivos anteriores, whitespace e Git final | PASS; verificação de hashes/prefixos e status ao encerrar a rodada |

## Estado final e retomada

Branch/HEAD/main mantidos. Estado final: **16 modificados e 7 untracked**, nada staged. O documento C.2 passa a modificado e este handoff é o único untracked novo; os 21 arquivos anteriores continuam presentes. Nos dois documentos anteriores editados houve somente acréscimo; os demais hashes foram preservados. Sem reset, stash, limpeza, staging, commit, merge, push, tag ou deploy.

Nenhuma ativação, app, UI ou banco diário foi executado/aberto. Não há hash de build novo nesta rodada. O release anterior não é implementação de ativação. **Smoke visual: BLOCKED/PENDENTE; P2 de Aprovações: PENDENTE. DEC-08 tem aprovação limitada, sem aceite técnico; DEC-08-A permanece aguardando decisão.**

Próximo passo: responder à política de admissão DEC-08-A. Depois, implementar e testar a barreira em todos os pontos de entrada, seguido do ativador e sua máquina de recuperação, sem promover schema antigo ou aceitar testes do C.2 como substitutos dos novos testes de crash/concorrência.

---

## Retomada — DEC-08-A aprovado e implementação — 16/10/2026

**Esta seção substitui o estado de bloqueio acima.** O proprietário respondeu explicitamente aprovando a opção 1: apenas bancos criados sob o protocolo de leases; bancos preexistentes continuam bloqueados para ativação até procedimento separado, explícito e seguro confirmado pelo proprietário. Schema do backup continua exatamente compatível. A aprovação foi registrada em DECISIONS_PENDING.md; não há autorização de adoção legada, upgrade, banco diário ou execução fora dos testes.

### Baseline, objetivo e preservação

Reconfirmados branch `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0` e `main` `21f1537e14706a42e8272f92cb4f4b6dab746640`. Após o handoff documental anterior, o estado de entrada desta retomada era **16 modificados/7 untracked**, sem staging. Objetivo: implementar o fluxo offline aprovado, validar somente em bancos temporários sintéticos e preservar todos os trabalhos anteriores.

### Arquivos desta implementação

- Novos `apps/api/database_leases.py`, `restore_activation.py`, `test_restore_activation.py`.
- `apps/api/memory_store.py`: origem somente na criação, leases por conexão, vida do runtime e invalidação de stores que apontam para inode anterior; recuperação antes de migrations.
- `apps/api/main.py`: runtime lease nos dois lifespans até encerramento do worker e erros operacionais seguros.
- `apps/api/backup_recovery.py`: lease compartilhada durante o snapshot; erro de estrutura normalizado para BackupError, mantendo validação estrita.
- `apps/api/backup_cli.py`: novo comando interativo `activate`, com ambos os caminhos explícitos e confirmação vinculada ao plano; backup/restore isolado permanecem disponíveis.
- `apps/api/e2e_mark_calendar_state.py`: helper exclusivamente sintético passa a respeitar manutenção e fechar conexões.
- Harnesses existentes: `test_native_app_api.py`, `test_local_security.py`, `test_calendar_simulator.py`, `test_knowledge_api.py`, `test_mission_import_identity.py`, `test_mission_read_revocation_races.py`, `test_missions_api.py`, `test_r5_trusted_state.py`, `test_review_api.py`, `test_selected_source_api.py`. Restarts encerram o runtime sintético anterior; clientes HTTP concorrentes compartilham o lifespan já ativo. Nenhuma assertion de autorização, dados, concorrência ou revogação foi removida/afrouxada para admitir segundo runtime escritor.
- Documentos DEC-08, C.2, este handoff e adendo no handoff de paginação.

### Contrato implementado

1. Arquivos de lock fixos `.NOME.maintenance.lock` e `.NOME.writer.lock` nunca são removidos. Ordem manutenção → writer, flock não bloqueante. Conexões normais e backup seguram manutenção compartilhada; runtime segura compartilhada mais writer exclusivo até o drain. Inicialização, recuperação e ativação usam manutenção exclusiva; falha em reservar recusa o acesso. Cada conexão é fechada antes de soltar sua lease.
2. `.NOME.lease-origin.json` é criado somente após a inicialização bem-sucedida de um banco que não existia, sob exclusividade. Inicializar arquivo existente não cria origem. Origem malformada ou banco registrado ausente recusam a operação pertinente; um banco registrado que desapareceu não é recriado silenciosamente. A origem é proveniência local cooperativa, não autenticação contra mesmo UID/admin ou prova de que software não cooperativo jamais abrirá esse caminho.
3. `prepare_activation` exige caminhos explícitos, autentica o arquivo AES-GCM/Argon2id e valida imagem, integridade, FKs, manifest completo/checksums e estrutura exatos. Sob exclusividade valida o atual e espaço. O CLI apresenta destino, hash do backup, manifest/protocolo e consequências; exige senha via getpass/TTY e digitação de `ATIVAR <SHA-256 completo>`. Esse digest vincula destino, arquivo autenticado, imagem, estado atual e schema/protocolo. A execução revalida a imagem e recusa plano antigo se houve escrita no ativo. Nenhum default/env seleciona o destino de ativação.
4. Caminhos com links simbólicos são recusados, arquivos devem ser regulares/privados/do proprietário, nlink=1; abertura usa O_NOFOLLOW e conferência de identidade por descriptor. Diretórios privados, staging no mesmo volume e rechecagem de inode do ativo precedem a troca. Espaço conservador: quatro vezes a soma do conjunto atual e imagem candidata, mais 16 MiB; não substitui tratamento de ENOSPC/EIO em I/O real.
5. SQLite recupera journal legítimo e consolida WAL por checkpoint TRUNCATE, sem busy/frames pendentes, muda para DELETE e fecha. Sidecars remanescentes ou reaparecidos antes da troca bloqueiam; nunca são apagados para forçar progresso. Validação dedicada não inicia migrations, worker ou scheduler.
6. Área de operação privada sob `.NOME.activation/ID` retém `rollback.sqlite3` independente e `rollback-ready.sqlite3` independente pronta para reinstalação; o candidato é outra cópia. Arquivos/diretórios recebem fsync. Rollback preservado não compartilha inode com o ativo. No candidato, automações ativas ficam pausadas/sem próxima execução e runs pending/deferred/retry_wait/running tornam-se superseded; capturas e workflows não são executados nem removidos.
7. Registro canônico estrito versionado com ID, hashes antigo/novo, schema/protocolo e estado: BUILDING → PREPARED → SWITCHED → COMMITTED, publicação por replace + fsync. PREPARED durável antecede replace do banco. Registro/parciais/staging são retidos em caso de falha, sem tentar ganhar espaço apagando evidências.
8. Todo startup consulta a pendência antes de criar/abrir para migrations e antes do worker. BUILDING válido aborta sem troca após consolidar/validar o atual. PREPARED/SWITCHED validam rollback e alvo: hash antigo conclui ROLLED_BACK; hash novo reinstala rollback-ready, sincroniza, valida e registra ROLLED_BACK. Crash na própria reversão pode ser repetido idempotentemente. Alvo ausente/inesperado, rollback inválido, registro obrigatório ausente/malformado, schema divergente ou I/O persistente bloqueiam. COMMITTED permite hash diferente após escritas legítimas, valida integridade/schema e nunca dispara rollback automático com perda de dados.
9. Rollbacks preservados e backups cifrados não são excluídos automaticamente. Só o arquivo rollback-ready é consumido por rename para reinstalar o ativo durante reversão pré-commit. Retenção/limpeza, admissão de banco preexistente e recuperação manual de evidência ambígua continuam fora desta implementação. O produto não oferece ativação por UI, voz, HTTP ou rota UDS.

### Testes e comandos

Os testes novos recusam resolução de banco default e usam caminhos explícitos sob tmp_path, fora do repositório. Subprocessos com `os._exit` são criados apenas pelo harness, com bancos sintéticos; nenhum processo do usuário é sinalizado. As regressões UDS também usam runtimes/caminhos sintéticos, sem abrir o aplicativo Tauri ou sua interface.

- Baseline C.2/memória: `rtk env UV_OFFLINE=1 JARVIS_DATABASE_PATH=/tmp/jarvis-dec08-unused-default-20261016/memory.sqlite3 uv run --locked --offline --python 3.12 pytest -q test_backup_recovery.py test_memory_store.py` — **67 PASS**.
- Iteração inicial de ativação: 105 PASS/7 FAIL. Correções: normalização de erro estrutural; duas referências incorretas ao campo de auditoria no harness. Quatro falhas de subprocesso decorreram da alteração do identificador do protocolo enquanto a rodada antiga ainda rodava; uma nova rodada com os módulos alinhados passou. Rerun específico dos 13 casos: **13 PASS**.
- Iteração integrada inicial: 324 PASS/4 FAIL; os quatro harnesses abriam runtimes simultâneos. Após correção de lifecycle: **4 PASS** no rerun específico.
- Rodada focada completa posterior: `pytest -q test_restore_activation.py test_backup_recovery.py test_memory_store.py test_main.py test_local_security.py test_native_app_api.py test_native_runtime_process.py test_native_ctr_partition.py test_local_automations.py test_workflow_executor.py` com o mesmo prefixo/env — **334 PASS**, duas depreciações existentes de TestClient/httpx/cookies.
- A revisão das demais 195 regressões revelou 14 falhas no mesmo padrão de harness (restart sobreposto ou segundo lifespan para cliente HTTP). Foram corrigidos os ciclos de vida sem relaxar assertions; execução final consolidada registrada abaixo.

Cobertura nova: sucesso e conteúdo/IDs preservados; rollback independente; banco preexistente/ausente; schema antigo/futuro/checksum/estrutura/corrupção/senha; confirmação obsoleta/incorreta e terminal não interativo; readers/writers/transação/backup/runtime/ativador concorrentes; lease de runtime ocioso em subprocesso; bloqueio de novas conexões/starts durante manutenção; espaço zero, ENOSPC/EIO/EXDEV/EACCES, escrita parcial/fsync/rename reais; permissões, symlink, hardlink, registro ausente/malformado/duplicado, hash inesperado/rollback inválido; WAL confirmado preservado no rollback, leitor bloqueando checkpoint e hot journal; crashes em cada fronteira instrumentada de escrita/fsync/publicação/troca e na própria reversão; recuperação repetida, startup antes de migrations, corrupção pós-commit sem rollback automático e pausa das automações sem replay.

### Limites e próximos gates

As leases são cooperativas, não proteção contra acesso direto não cooperativo do mesmo UID/admin, inclusive binário anterior que ignore o protocolo. A política aprovada bloqueia a ativação de bancos preexistentes; não cria autorização de admissão nem transforma marcador em prova contra adulteração local. Testes de crash usam saída abrupta de processo e fsync no filesystem local; não simulam perda física de energia, defeito de hardware ou perda do volume, nem substituem auditoria independente de durabilidade/APFS. Staging/rollback permanecem plaintext privado, sem promessa de apagamento seguro. Evidência ambígua fica preservada e bloqueada, sem procedimento automático inventado para removê-la.

Sem migrations/dependências novas, sem alterações Rust/frontend nesta retomada, sem build novo e sem executar binário. O release anterior não comprova inclusão/empacotamento deste código Python. Nenhum banco diário ou fora dos testes foi aberto/ativado. Sem merge, push, tag, deploy, staging, commit, reset, stash ou limpeza. UDS-only, PID/HMAC/CTR/replay, allowlists e separação capability/sessão/grant não foram alterados. **Smoke visual: BLOCKED/PENDENTE. P2 de Aprovações: PENDENTE.** Próximo gate: revisão independente do ativador/leases/durabilidade antes de uso real; adoção de banco preexistente requer procedimento e autorização próprios.

### Resultado consolidado e Git final

- `rtk env UV_OFFLINE=1 JARVIS_DATABASE_PATH=/tmp/jarvis-dec08-unused-default-20261016/memory.sqlite3 uv run --locked --offline --python 3.12 pytest -q` em `apps/api`: **529 PASS em 182,57 s**, duas depreciações existentes (TestClient/httpx e cookies por request), nenhuma falha. Inclui memória, backup, segurança, sessões/grants, isolamento, missões, fontes/proveniência, reviews, automações, workflows, runtime UDS/PID/HMAC/replay e partições CTR.
- Depois do último reforço de rechecagem de caminhos e do caso de symlink de diretório introduzido antes da troca: mesmo prefixo/env, `pytest -q test_restore_activation.py`: **134 PASS em 99,31 s**. É repetição da suíte de ativação, não 134 regressões adicionais disjuntas dos 529. Nenhum código foi alterado depois dessa execução; somente este registro documental.
- `rtk git diff --check`, whitespace dos arquivos novos e preservação das alterações anteriores: **PASS**. Para o arquivo de teste nativo já modificado antes da rodada, os bytes anteriores também foram conferidos por SHA-256 após reverter apenas o novo ajuste de import/helper em memória; as assertions e alterações anteriores continuam preservadas. Documentos anteriores receberam adendos, sem apagar o histórico. Todos os untracked anteriores permanecem presentes.
- Branch, HEAD e main mantidos. **30 modificados / 10 untracked**, nada staged. Os três untracked novos desta retomada são os dois módulos e o teste de ativação; o handoff de restore já existia no baseline de retomada. Sem build novo, capturas ou demo visual. Nenhuma ativação em banco fora dos testes.

```text
 M apps/api/backup_cli.py
 M apps/api/backup_recovery.py
 M apps/api/e2e_mark_calendar_state.py
 M apps/api/local_automations.py
 M apps/api/main.py
 M apps/api/memory_store.py
 M apps/api/native_app_api.py
 M apps/api/native_runtime.py
 M apps/api/test_calendar_simulator.py
 M apps/api/test_knowledge_api.py
 M apps/api/test_local_security.py
 M apps/api/test_mission_import_identity.py
 M apps/api/test_mission_read_revocation_races.py
 M apps/api/test_missions_api.py
 M apps/api/test_native_app_api.py
 M apps/api/test_r5_trusted_state.py
 M apps/api/test_review_api.py
 M apps/api/test_selected_source_api.py
 M apps/api/workflow_executor.py
 M apps/desktop/src-tauri/src/lib.rs
 M apps/desktop/src-tauri/src/runtime_manager.rs
 M apps/desktop/src-tauri/src/transport.rs
 M apps/desktop/src/App.tsx
 M apps/desktop/src/runtimeCommand.ts
 M apps/desktop/tests/runtimeCommand.test.mjs
 M docs/GATE2_0C_2_BACKUP_RECOVERY.md
 M docs/g6/DECISIONS_PENDING.md
 M docs/g6/LOCAL_AUTOMATIONS.md
 M docs/g6/WORKFLOW_EXECUTOR.md
 M docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md
?? apps/api/database_leases.py
?? apps/api/fixtures/automation_validation_error.txt
?? apps/api/fixtures/scope_invalid_error.txt
?? apps/api/fixtures/workflow_page_v1.txt
?? apps/api/restore_activation.py
?? apps/api/test_restore_activation.py
?? apps/desktop/tests/workflowHistory.test.mjs
?? docs/g6/LOCAL_AUTOMATION_ERRORS_2026-10-14.md
?? docs/g6/RESTORE_ACTIVATION_2026-10-16.md
?? docs/g6/WORKFLOW_HISTORY_PAGINATION_2026-10-14.md
```

## Reconciliação de exclusões posteriores ao backup — 22/10/2026

A biblioteca offline `prepare_activation(..., storage_key=chave_em_memoria)` lê o banco atual explícito sob manutenção exclusiva e lease de escritor, autentica o snapshot selado e reconcilia seu ledger com o backup. `activate(..., storage_key=...)` revalida plano, estado atual e união sob as mesmas barreiras antes de criar a candidata. A identidade é `(categoria, domínio, ID estável)`; não se usa relógio para arbitrar revisões. Decisão repetida com mesma revisão/digest/operação é idempotente. Mesmo ID com decisões divergentes, operação inválida ou revisão da linha superior à exclusão falha fechado: o formato não comprova linhagem. Linhas de revisão menor são removidas; na mesma revisão o digest precisa casar antes da remoção.

A união é aplicada e validada no SQLite em memória, antes de qualquer ativação, e fica no ledger do banco resultante para backups futuros. Busca/origem consultam as tabelas atualizadas; não há FTS ou cache persistente independente de texto. Handles da geração anterior são recusados. Saídas já copiadas para workflows, exports ou outros bancos não são purgadas.

Para destino selado, candidata, rollback e rollback-ready são envelopes cifrados, ainda que os nomes históricos terminem em `.sqlite3`; não se cria staging persistente em claro. A chave explícita não entra no plano/journal, disco, ambiente ou argumentos de subprocesso. Nos ensaios, chaves sintéticas atravessam processos somente por pipe anônimo. O protocolo BUILDING/PREPARED/SWITCHED/COMMITTED mantém rollback independente; antes de COMMITTED durável, a recuperação volta ao banco anterior. COMMITTED não sofre rollback automático. `initialize` e unlock fora do runtime recuperam antes das migrações. Unlock dentro de runtime já com lease compartilhada recusa journal pendente e exige recuperação offline exclusiva; backup também recusa ativação pendente. Se nem o primeiro estado foi publicado, evidência incompleta bloqueia recuperação automática e o primário anterior é preservado. Locks são cooperativos; isso não protege contra software malicioso do mesmo usuário ou corrupção física/ausência de artefatos.

O CLI `activate` continua adaptador SQLite legado, sem novo canal de transferência de chave; a ativação selada é API Python offline, sem rota HTTP, comando IPC ou janela. O snapshot consistente de alvo legado em WAL normaliza em RAM apenas os dois marcadores de formato de journal copiados pela API de backup: WAL e banco originais não são modificados nessa leitura. Checkpoint e substituição permanecem no protocolo de ativação existente.

Backup anterior ao ledger, ou ledger vazio, exige `confirm_legacy_resurrection=True` antes de staging/ativação; no CLI legado a opção é `--confirm-legacy-resurrection`. O aviso informa que conteúdo excluído pode voltar. Isso também é exigido, conservadoramente, quando existe ledger atual. Migrações conhecidas do backup são aplicadas só em memória; schema desconhecido/incompatível falha fechado. O banco atual precisa do schema suportado e da origem de leases existente. Restauração isolada, sem banco atual explícito, continua sem conhecer exclusões posteriores ao snapshot. Não há expiração de tombstones, sanitização de archives históricos, wipe físico, remoção de exports ou garantia para consumidores externos.

Ensaios somente em bancos/backups sintéticos temporários novos; nenhum banco diário, Keychain, .env, rede, provider, OAuth ou efeito externo. Smoke visual: NOT TESTED/BLOCKED, janela não aberta. Mobile continua BLOCKED por dependências ausentes, sem nova execução; APK e assinatura fora. Não é aceite para uso ou distribuição.

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
