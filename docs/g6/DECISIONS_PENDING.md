# Decisões pendentes e restrições

Este registro distingue restrições confirmadas pelo produto de opções técnicas ainda sem aprovação. G6.0 não cria ADR para item em aberto.

## Restrições já definidas

| ID | Restrição | Consequência |
|---|---|---|
| R-01 | Clientes não decidem autorização; backend Victor OS é a autoridade de produto. | Nenhum SDK/UI nativo pode substituir validações do servidor. |
| R-02 | G5 permanece aceito no escopo local, sintético, monoprocesso ADR-010. | Não afirmar account identity, multiworker, host-admin protection ou remote security. |
| R-03 | API fica loopback-only no próximo escopo local. | Android não acessa Mac por LAN ou túnel. |
| R-04 | Voz começa com PTT; não usa wake word nesta linha. | Microfone não é habilitado por G6.0. |
| R-05 | Áudio bruto não fica armazenado por padrão; voz não aprova ações sensíveis sozinha. | Aprovação visível e revalidação do servidor são mandatórias. |
| R-06 | Sem conta real, OAuth, API externa paga, cloud, sync, push, deployment ou dados pessoais nesta sprint. | Nenhuma dependência/credencial/provider novo. |

## Decisões técnicas pendentes

| ID | Pergunta que precisa de resposta | Opções/critério | Bloqueia |
|---|---|---|---|
| DEC-01 | Como empacotar Python API para sidecar macOS? | PyInstaller conforme referência Tauri; outra distribuição congelada; avaliar tamanho, compatibilidade arm64/x86_64, supply chain, notarização e debug. Nenhum método escolhido. | PR de sidecar distribuível G6.1 |
| DEC-02 | Qual canal do parent receberá porta e readiness do child? | stdout estruturado com challenge, pipe local ou socket IPC privado; exigir posse do child, nonce, parse restrito e ausência de segredo em log. | Runtime Manager G6.1 |
| DEC-03 | Porta dinâmica ou endpoint IPC intermediado? | Bind loopback efêmero mantido pelo child versus bridge Tauri estreita; avaliar origem/cookies, CSP, superfície de comandos e port collision. Nunca conectar em serviço existente. | Transporte autenticado G6.1 |
| DEC-04 | Qual é a origem efetiva do WebView Tauri em build distribuível? | Inspecionar URL/scheme do artefato; autorizar exatamente essa origem ou escolher IPC tipado; sem CORS wildcard, null ou reflection. | Primeiro request autenticado G6.1 |
| DEC-05 | Como sinalizar readiness real? | Health interno autenticado por challenge, report pelo pipe e validação de versão/DB; endpoint atual /health é DEMO mock e não é suficiente. | UI Ready G6.1 |
| DEC-06 | Como versionar API já existente sem prefixo? | Freeze OpenAPI e compatibilidade por schema; escolher path/header e política de deprecation antes de client release. | Geração de client G6.1 |
| DEC-07 | Tipos gerados ou SDK comum? | Começar com OpenAPI->TS reprodutível; SDK somente quando dois clientes API estiverem conectados e compartilharem transporte. | PR integração da Web e Mac |
| DEC-08 | Política de backup/migração do SQLite do .app? | Backup consistente, upgrade, falha, recuperação e downgrade; não assumir migration reversível. | Release atualizável G6.1 |
| DEC-09 | Quais providers de voz usar em cada plataforma/idioma? | API de sistema, provider externo, ou provider licenciado; medir disponibilidade offline, locale, qualidade, dados enviados, preço, licença e interrupções. Nenhum selecionado. | G6.2 real |
| DEC-10 | Aprovação por voz pode existir? | Contrato inicial exige aprovação visual explícita. Qualquer proposta de gesto vocal futuro demanda análise de assurance e aceite próprio; backend continua obrigatório. | Feature de voice approval |
| DEC-11 | Qual mecanismo Tauri protege single instance e saída/crash? | Runtime Manager próprio + plugin suportado; separar single-instance da gestão do child. Testar bundle macOS. | G6.1 |
| DEC-12 | Qual subgate escolhe modo de continuidade Android? | Comparar A–E em G6.4 com privacidade, segurança, custo, disponibilidade e recuperação. | Qualquer sync/remoto |
| DEC-13 | Qual política de identidade e recuperação? | Identidade produto vs usuário local, enrollment, sessão por device, chave, revoke offline, perdida/recuperada. | G6.4 |
| DEC-14 | Quais IDs e retenção para conversation? | **Resolvido nesta candidata;** ver decisão abaixo e ADR-013. O ID é opaco, pertence ao owner e fica no store cifrado por no máximo 24 horas de inatividade. Não há histórico de voz/transcrição. | Continuidade de leitura local; voice history segue fora do escopo |
| DEC-15 | Qual custo recorrente é aceitável após protótipo? | STT/TTS, hosting, storage, sync e push têm cenários de preço e consentimento separados. R$0 é objetivo do protótipo, não previsão de produção. | Provider pago/serviço remoto |

## Decisões que não devem ser confundidas

## DEC-14 — Identificador opaco para conversa local (2026-10-22)

**Estado: RESOLVIDO para conversa local sintética da candidata.** O servidor emite um ID aleatório de 128 bits, codificado como 32 caracteres hexadecimais minúsculos. O snapshot SQLite cifrado persiste somente `conversation_id`, principal constante `owner`, `domain_id` sintético fixo, `created_at`, `last_seen_at` e `expires_at`. Não são gravados transcrição, pergunta, resposta, prompt, fonte, token de sessão, grant ou conteúdo de provider.

A expiração é deslizante: cada leitura autorizada prolonga até 24 horas de inatividade; abertura remove IDs expirados. `resume` devolve o ID não expirado mais recente para o principal/domínio fixo ou cria um novo; `new` sempre cria outro ID. Lock/fechamento limpa estado de gateway e sessões/grants voláteis, mas mantém a linha cifrada até expirar. Reabrir o app exige desbloqueio e uma sessão nova; a sessão anterior e seus grants não são retomados. A autorização é validada novamente no servidor em cada chamada. A decisão não inclui transcript nem histórico de voz.

Revalidação de regressão em 22/10/2026 na candidata: `test_front2_continuity.py` executou sem exclusão (4 passed) e valida ID opaco/metadados mínimos no store cifrado, ausência de transcrição/prompt/resposta/fontes/token/grant persistidos, expiração e reabertura sem autorização anterior. O grupo focado de cifra, categorias, tombstones/restore, gateway, leitura fundamentada, loop, IPC/API e processo passou: 141 passed, 1 aviso. A suíte pytest completa da API foi executada e falhou: 263 failed, 293 passed, 178 errors; as falhas incluem fixtures legadas que instanciam o store sem chave ou esperam SQLite claro, e `restore_activation` acessa caminhos de banco como SQLite claro. `cargo fmt --all -- --check` passou depois da formatação de 50 hunks estritamente de estilo em `runtime_manager.rs` (43) e `transport.rs` (7); os diffs Rust completos dos dois arquivos foram revisados. `cargo test --locked --offline --features mac003-production-supervisor-test` passou com 112 testes unitários e 1 integração Rust→FastAPI/UDS; 9 seguem ignorados. TypeScript IPC passou com 26 testes; `tsc --noEmit` e build de produção passaram. O Keychain real não foi usado nem alterado; provider real não foi chamado; smoke visual não foi executado. A falha da suíte completa impede declarar o contrato global de restore/regressão aprovado.

Confirmação em 23/10/2026, só do caminho de conversa: a interface desktop já pergunta pelo IPC autenticado. Depois de reiniciar ou bloquear o store, ficam voláteis a sessão, os grants, o texto visível do gateway, prompts, respostas, fontes e tokens. Permanece no snapshot cifrado, até expirar, apenas `conversation_id`, `owner`, `domain_id`, `created_at`, `last_seen_at` e `expires_at`. Reabrir o ID não reautoriza a sessão anterior. A suíte API completa desta data passou com 840 testes e 2 warnings. Smoke visual NOT TESTED. Isso não declara uso nem distribuição.

- Um port number aleatório não é autenticação; a posse do child, o handshake e a validação de origem também importam.
- Um Keychain/Keystore não cria identidade de usuário nem decide grants.
- Um transcript correto não é um ato de aprovação e um ID de missão não é prova de acesso.
- Um ícone Capacitor/permission INTERNET não torna API local alcançável pelo Mac.
- Uma resposta em cache não confirma que revisão continua atual; version e digest devem ser revalidados.
- Tauri segue como candidato atual porque já existe scaffold; trocar framework exige justificativa concreta num ADR, não uma preferência estética.

## ADRs

Nenhum ADR G6 novo é criado nesta entrega. DEC-14 fica resolvido para leitura local sintética no ADR-013 e acima; port, origem, empacotamento, identity remota e provider continuam pendentes. Quando uma decisão de implementação for tomada num subgate, registrar contexto, alternativas, consequências, threat boundary, rollback e evidência no ADR correspondente.


## DEC-08 — Proposta de ativação segura de restore (2026-10-14)

**Estado: PROPOSTA PARA REVISÃO; DEC-08 NÃO APROVADO.** Esta seção complementa a decisão pendente, sem alterar o aceite C.2 ou autorizar ativação/dados pessoais. Baseline observado: `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`; main `21f1537e14706a42e8272f92cb4f4b6dab746640`. Os 14 modificados/5 untracked anteriores permanecem preservados.

### Fatos observados no código

- [C.2](../GATE2_0C_2_BACKUP_RECOVERY.md) autoriza somente backup cifrado e restore isolado sintético. `backup_cli.py` oferece apenas `backup`/`restore`, usa `getpass` interativo e resolve o banco por `default_database_path()`; override pode mudar esse destino. Não existe comando de ativação.
- `backup_recovery.py`: `_open_archive` autentica header canônico/AAD e ciphertext JARVISBK v1, AES-GCM/Argon2id, antes de gravar plaintext; limites são 256 MiB de imagem e limite próprio do arquivo. `_validate_snapshot` exige `integrity_check`, `foreign_key_check`, **igualdade do manifest completo de versões/checksums com as migrations atuais** e schema estrutural. O header não declara versão do schema: esta vem de `schema_migrations` na imagem autenticada.
- O documento C.2 relata o marco original de três migrations. A candidata contém **18**, até `0020_local_automations`, incluindo `0019_workflow_tasks` e sem `0018`; o código atual exige as 18. Não aceita simplesmente qualquer backup antigo como upgrade. Histórico anterior não foi reescrito.
- `restore_backup` grava/valida staging privado, publica por hard link **sem substituir**, sincroniza diretórios e retorna um `restores/restore-v1-*/memory.sqlite3` novo. A limpeza de `-wal`, `-shm`, `-journal` é do staging privado, não autorização para limpar sidecars de banco ativo.
- `memory_store.py:224–244` habilita WAL, usa synchronous FULL e aplica migrations durante `initialize`; cada migration tem transação própria (`277–324`), não uma transação única do upgrade inteiro. `transaction` usa BEGIN IMMEDIATE e fecha a conexão ao final (`463–475`). Não há barreira interprocesso de ativação nos fluxos inspecionados; transação SQLite não protege uma troca de nomes de arquivos.
- `main.py:211–225` inicia reconciliação e worker; `local_automations.py:753–760` chama `startup_reconcile` e `run_due`. Abrir o app não é validação neutra de restore. Sessões/grants são voláteis; conteúdo/argumentos/resultados e rollback local continuam sem cifra de conteúdo.
- `test_backup_recovery.py` contém testes temporários de WAL/concorrência, autenticação, schema, permissões, colisões e escrita/fsync. São testes de backup/restore **isolado**, não de ativação. O handoff [da candidata](INTEGRATION_CANDIDATE_2026-10-13.md) reporta upgrade `0019 → 0020` temporário; não prova ativação nem foi reexecutado nesta rodada.

### Opções e recomendação proposta

| Opção | Vantagem | Limite |
|---|---|---|
| Manter restore isolado e usar override para inspeção | Preserva o fluxo existente | Não ativa banco diário nem fecha a política de ativação; abrir app pode executar scheduler |
| **Ativação offline no caminho estável, staging + rollback + registro durável** | Mantém resolução atual do banco; troca um arquivo preparado | Exige barreira de manutenção comum, tratamento WAL e recuperação antes de startup |
| Diretórios por geração e ponteiro ativo atômico | Isola arquivos/sidecars por geração | Altera resolução em runtime, CLI e backup; amplia compatibilidade e escopo |

**Recomenda-se a segunda opção**, primeiro somente para schema exatamente compatível e testes sintéticos. Não oferecer troca online, symlink de destino, edição de migration aplicada ou downgrade por SQL reverso. Upgrade de backup legado é extensão separada: validar contra manifest histórico aprovado, migrar apenas cópia isolada e validar contra manifest alvo. Isso ainda não existe; o validador atual deve continuar estrito. Downgrade requer imagem preservada **e runtime compatível**, com aprovação da possível perda de gravações posteriores. DEC-08 cobre política mais ampla de atualização; aprovar este desenho não prova todos os gates de release.

### Pré-condições e ordem proposta (não executada)

1. **Preparar sem tocar no ativo.** Autenticar/restaurar por C.2 para área isolada; revalidar imagem, schema e checksums. Selecionar explicitamente restore e destino `stable` ou `override`; nunca inferir destino diário de variável de ambiente. Confirmação do proprietário deve vincular identidade/hash da imagem, manifest/runtime, destino e consequência de substituir o estado atual. Não passa senha por WebView/argv/log; senha do backup não é G5 nem chave de armazenamento ativo.
2. **Reservar manutenção.** Todos os pontos que abrem o banco (startup web/nativo, store, CLI) devem respeitar uma lease de manutenção em arquivo fixo, privado e de inode estável: uso normal/backup readonly segura lease compartilhada durante toda a abertura; ativador exige exclusiva. Um writer lease separado deve impedir segundo runtime escritor; ordem de aquisição manutenção → writer. A ativação exige app/child encerrados cooperativamente, operações/scheduler drenados e conexões fechadas; não matar processo nem confiar apenas em PID/socket/lsof. Launcher bloqueia novos starts. Versão antiga que não respeite o contrato, timeout ou posse incerta: **recusar**. Esses mecanismos são requisitos novos, não garantias atuais; limites same-UID/admin permanecem.
3. **Consolidar WAL e preservar o anterior.** Com exclusividade, SQLite deve recuperar journal legítimo se necessário e concluir checkpoint TRUNCATE sem busy/frames pendentes; fechar conexão e verificar que não resta WAL necessário. Não apagar WAL para forçar sucesso, não transportar sidecars do restore para o alvo e não fazer checkpoint dentro de BEGIN IMMEDIATE. Se não puder provar consolidação, parar preservando o conjunto original. Guardar imagem anterior consistente, validada e independente em diretório rollback privado; copiar, não compartilhar inode por hard link com futuro ativo. Preparar também cópia independente pronta para reinstalar rollback, antes da troca. Banco atual corrupto/incompatível exige recuperação separada: preservar arquivos, não substituir automaticamente.
4. **Preparar publicação no mesmo filesystem.** Copiar candidato para staging novo no volume do alvo; revalidar após cópia, fechar conexões, consolidar seus sidecars por SQLite e manter imagem completa autônoma. Exigir dono/permissões 0700/0600, arquivos regulares, nomes fechados, no-follow e rechecagem de identidade por descriptor; rejeitar symlinks, colisões, hard links inesperados e mudança de diretório/arquivo. Não reutilizar diretamente o inode que o restore atual publica por link. Verificar espaço para todas as cópias (candidato, rollback preservado, rollback reinstalável, temporários/WAL/margem), não só 256 MiB. Reserva/preflight não garante espaço: tratar ENOSPC em cada operação.
5. **Registrar antes de trocar.** Fsync de imagens e diretórios; gravar registro canônico versionado `PREPARED` por publicação atômica + fsync do diretório. Contém só ID, estado, hashes/identidades, manifest/runtime e nomes relativos fixos, sem dados/segredos. **Todo startup verifica pendência antes de `initialize()`**, para não criar banco vazio ou migrar durante recuperação. Não há atomicidade conjunta de banco e registro: recuperação resolve esse intervalo.
6. **Trocar e validar sem worker.** Somente com alvo antigo consolidado e sem sidecars conflitantes: rename/replace atômico do candidato preparado para o caminho ativo, fsync do diretório, registrar `SWITCHED` duravelmente. Validar o novo alvo com rotina SQLite dedicada, sem startup do app/migrations tardias/scheduler; fechar conexões. Registrar `COMMITTED` + fsync antes de liberar manutenção. Nenhuma migração é aplicada no banco anterior como atalho. Falha de fsync mantém operação pendente, sem anunciar sucesso.
7. **Retomar deliberadamente.** Nova geração de runtime, sessão/grants/capability novos; consentimentos antigos não autorizam execução. Modo pós-restore deve suspender automações restauradas até revisão/retomada explícita do proprietário, sem replay de efeitos ou recuperação automática de missed-run. Só depois das validações liberar escritas de negócio. Reter ao menos rollback da última ativação; remoção/retenção adicional exige política aprovada. Não prometer cifra do rollback ou apagamento físico seguro.

### Interrupção, incompatibilidade e rollback propostos

| Evidência durável ao recuperar, sob manutenção exclusiva | Ação permitida |
|---|---|
| `PREPARED`/`SWITCHED`, alvo coincide com hash antigo | Manter antigo; operação não comprometida; preservar candidato para diagnóstico |
| `PREPARED`/`SWITCHED`, alvo coincide com novo (crash entre rename e registro) | Reinstalar rollback pré-validado por troca atômica + fsync; validar antes de registrar reversão. Este rollback pré-commit integra a confirmação original |
| Operação pendente identificada com registro obrigatório ausente/malformado, alvo faltante, hash inesperado ou rollback inválido | Bloquear startup/escritas e preservar evidências; não adivinhar, criar banco vazio ou sobrescrever |
| `COMMITTED` durável | Startup valida compatibilidade/integridade; hash da imagem inicial não é exigido após escritas legítimas. Falha posterior não permite rollback automático com perda de dados |

Ausência de histórico de ativação em instalação normal não é pendência: startup normal continua permitido; staging órfão isolado não vira banco ativo. Incompatibilidade futura/legada, checksum divergente, corrupção, senha errada e permissões inseguras são recusas antes da troca. ENOSPC/erro de IO antes do rename mantém antigo; depois dele usa registro e rollback preparado, sem depender de nova cópia ou apagar evidências para ganhar espaço. A reversão repete a barreira de conexões e tratamento seguro dos sidecars; nunca combina WAL da candidata com imagem antiga. Se não puder consolidar esses arquivos ou se rollback também falhar, permanecer bloqueado. Rollback posterior a escritas preserva primeiro o estado novo e exige decisão explícita; não mescla notas/missões nem inventa migrations reversíveis. Fsync/rename precisam de prova no filesystem suportado (APFS/macOS); sem promessa de recuperação contra perda física do volume/hardware.

### Critérios de aceite e testes para implementação posterior

- Harness recebe caminhos explícitos sob `tmp_path`, fora do repo, com guard que recusa qualquer caminho fora da raiz sintética; monkeypatch dos defaults falha caso seja chamado. Nunca executar CLI padrão/abrir banco diário. Fixtures incluem capturas, workflows e automações sintéticos; validar tabelas, IDs, hashes e estados finais, não só saída textual.
- Interprocesso: runtime vivo, transação em curso, backup concorrente, segunda instância, tentativa de restart e ativação dupla; nenhum escritor atravessa manutenção. Processos sintéticos, barreiras determinísticas, sem UI, rede ou provider. Preservar backup online normal fora da ativação.
- WAL: commits ainda só no WAL, leitor que impede checkpoint, hot journal, sidecar inseguro/antigo, crash durante consolidação; nunca perder commit confirmado nem anexar WAL antigo à imagem nova.
- Matriz de schema: atual; antigo rejeitado; futuro/checksum/estrutura adulterados; upgrade em cópia somente quando manifest histórico aprovado existir. Falha entre migrations não altera ativo/rollback. Runtime de downgrade compatível e incompatível.
- Injetar crash de subprocesso sintético antes/depois de **cada** write/fsync/rename/estado, inclusive rename bem-sucedido com registro ainda PREPARED. Recuperação repetida é idempotente: antigo ou novo completo, nunca mistura/banco vazio; casos ambíguos ficam bloqueados. Testar falta de espaço, escrita parcial, fsync/permissão/collision/EXDEV, identidade alterada e falha no próprio rollback.
- Pós-restore: validação não roda scheduler; notas/workflows preservados; sessão/grant antigos rejeitados; automações não disparam sem retomada explícita. Logs/mensagens com códigos fechados, sem conteúdo/chaves/senhas. Rollback não compartilha inode e permanece recuperável após novas escritas.

**Decisão requerida:** proprietário aprovar opção, escopo inicial de schema exato, confirmação/retomada e retenção de rollback; auditoria validar desenho de leases e durabilidade/recuperação antes da implementação. Sem essa decisão, ativação continua bloqueada.

### Handoff desta rodada documental

Somente este documento recebeu adição; leituras de Git/AGENTS, backup/restore/store/startup, backlog e handoff, sem execução de código de backup/restore. Verificação documental `rtk git diff --check` e whitespace: **PASS**. Testes de ativação: **NOT TESTED / não implementados**; evidências anteriores são relatos, não reexecução. Nenhum banco/processo/app foi aberto, substituído ou interrompido, nenhuma dependência/migration foi alterada; sem commit/merge/push/tag/deploy. **Smoke visual e P2 de Aprovações: PENDENTES.** Próximo gate: revisão explícita desta proposta.

## DEC-08 — Aprovação limitada e decisão de transição — 2026-10-16

**Estado atual: OPÇÃO RECOMENDADA APROVADA NO ESCOPO ABAIXO; IMPLEMENTAÇÃO BLOQUEADA NA DECISÃO ADICIONAL DEC-08-A.** O estado de proposta de 14/10 acima é histórico. Esta atualização registra a instrução explícita do proprietário de 16/10; não constitui aceite técnico da implementação, que ainda não existe.

Foi aprovada a ativação offline no caminho estável, com staging, rollback independente e registro durável, **somente para backup com schema exatamente compatível** com o runtime/migrations atuais. A autorização inclui validação integral antes da troca, exclusão de acessos concorrentes, tratamento de WAL/sidecars, checagem de caminhos/espaço/integridade, confirmação explícita no produto e preservação de backup/rollback sem exclusão automática. Não aprova upgrade de schema, backup com schema antigo, downgrade, uso de dados pessoais, ativação nesta sessão ou execução fora de testes sintéticos temporários. O DEC-08 mais amplo permanece parcialmente aberto.

### DEC-08-A — Admissão de bancos já existentes no protocolo de manutenção

O passo 2 da proposta exige recusar versão antiga sem suporte às leases e não aceitar apenas PID/socket/lsof como prova de exclusividade. O código atual não mantém uma lease durante a vida do runtime: `main.py` inicia o store/worker sem essa reserva; `memory_store.py` abre conexões SQLite por operação e fecha-as ao terminar; o backup abre uma conexão própria somente leitura. Um processo antigo pode estar vivo entre conexões e escrever novamente depois de uma inspeção que não encontrou locks SQLite.

Um probe com banco temporário sintético confirmou o limite: um processo usando o `SQLiteMemoryStore` atual inicializou o banco, ficou aguardando sem conexão aberta e gravou auditoria quando outro processo já mantinha `flock(LOCK_EX|LOCK_NB)` em um novo arquivo de manutenção. A operação não envolveu app/UDS, banco diário ou restore. Uma lease nova só coordena os pontos de entrada que passaram a respeitá-la; criar um marcador no banco existente não comprova que versões anteriores foram encerradas.

**Decisão adicional solicitada, ainda sem resposta:**

1. **Proposta recomendada:** primeira entrega admite ativação apenas de bancos criados sob o novo protocolo de manutenção; recusa bancos preexistentes sem admissão comprovada. Adoção de bancos existentes fica em decisão posterior. Trata-se da origem do banco ativo, não de autorizar backups com schema antigo.
2. Alternativa que exige aprovação explícita da limitação: definir uma etapa de adoção offline de bancos existentes, com declaração do proprietário de encerramento das versões antigas. Essa declaração não se torna prova automática contra um binário antigo que ignore as leases; não pode ser apresentada como a mesma garantia da primeira opção.

Nenhuma das duas opções foi escolhida implicitamente. Conforme a instrução para parar diante de decisão não coberta, não foram introduzidos engine de ativação, leases, comando de produto ou mudança no startup. A implementação deve retomar apenas após resolver DEC-08-A, mantendo o schema exato e os demais requisitos aprovados. Evidências, comandos e estado preservado: [RESTORE_ACTIVATION_2026-10-16.md](RESTORE_ACTIVATION_2026-10-16.md).

## DEC-08-A — Opção 1 aprovada pelo proprietário — 2026-10-16

**Atualização vigente: DEC-08-A RESOLVIDO, OPÇÃO 1 APROVADA; implementação retomada.** Os registros de bloqueio anteriores são históricos. O proprietário confirmou explicitamente: somente bancos criados sob o novo protocolo de leases podem ser ativados; bancos preexistentes ficam bloqueados para ativação até existir procedimento separado, explícito e seguro de manutenção ou migração confirmado pelo proprietário. A compatibilidade do schema do backup deve continuar exata. Não se criou procedimento de admissão ou upgrade nesta rodada.

Implementação Python: leases permanentes por destino, reserva durante conexões/backup e vida do runtime, origem registrada somente na criação de banco novo; ativador offline no caminho estável com staging, rollback preservado e cópia independente pronta para reinstalação, estados duráveis e recuperação antes de migrations/worker. O produto oferece `backup_cli.py activate ARQUIVO_ABSOLUTO --database DESTINO_ABSOLUTO`, somente em terminal interativo, senha via getpass e confirmação digitada vinculada por SHA-256 ao backup, imagem, estado atual, schema/protocolo e destino. Nenhum destino de ativação é inferido de `JARVIS_DATABASE_PATH`.

Automações ativas restauradas passam a pausadas, sem próxima execução; runs não concluídos passam a superseded. Retomada continua dependente da ação explícita existente do proprietário. Backup cifrado e rollback preservado não são removidos automaticamente; a cópia rollback-ready é consumível exclusivamente na recuperação pré-commit. Banco preexistente pode continuar em uso normal, mas inicializá-lo não cria registro de origem para ativação.

Pendências ambíguas/corruptas bloqueiam startup e escrita, em vez de criar banco vazio. Antes de COMMITTED, a recuperação sob exclusividade aborta BUILDING ou restaura a imagem anterior se a troca já ocorreu; depois de COMMITTED, valida integridade/schema sem exigir hash inicial após escritas legítimas e sem rollback automático. Limite: leases são cooperativas; software malicioso do mesmo UID/admin que ignore locks ou falsifique arquivos fica fora da garantia, e a restrição de origem não é autenticação contra esse adversário. Testes de crash de processo não constituem prova de perda física de energia/volume. Evidências finais e limites no [handoff de implementação](RESTORE_ACTIVATION_2026-10-16.md). Smoke visual e P2 de Aprovações permanecem pendentes; DEC-08 amplo não está integralmente encerrado.
