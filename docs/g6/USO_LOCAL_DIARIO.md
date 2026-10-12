# Uso local diário

Baseline da `main`: `21f1537e14706a42e8272f92cb4f4b6dab746640`.
Candidata anterior: `feat/jarvis-uso-local-diario` em `22f5decde620cbbe6d6e3017616e9e1b96961967`.
Worktree desta candidata: `feat/jarvis-gate-uso-diario-local`, isolada em `/Users/vic/.codex/worktrees/jarvis-daily-local-gate-20261012/Jarvis-Victor-OS`. Sem fast-forward, push, tag ou deploy.

O aplicativo continua em UDS, protocolo 3, com HMAC antes da descriptografia. Não há listener TCP, envio de e-mail ou criação de evento.

## O que dá para usar hoje

- Agora grava, edita e apaga ideias de até 80 caracteres no SQLite. Sem `JARVIS_DATABASE_PATH`, o arquivo é `~/Library/Application Support/Jarvis/memory.sqlite3`, com diretório `0700`, arquivo `0600` e sem fixtures.
- Inbox mostra runtime, canal UDS, Gmail, Google Calendar e o calendário simulado. Os dois primeiros conectores reais ficam não conectados.
- Missões lê só com `mission:read` explícito em `dom_synthetic_a`.
- Aprovações pede `mission:review` somente depois da confirmação `review-local`. Se a fila estiver vazia, uma confirmação separada permite criar um único rascunho sintético local. “Conferir conteúdo” busca o snapshot completo pela revisão e SHA esperadas; conteúdo retido, divergente ou grande demais é recusado sem truncamento. Após ler o conteúdo, a aprovação exige confirmação em diálogo nativo do macOS, montado no Rust a partir do snapshot autoritativo; o WebView não envia um booleano de confirmação. Só então o backend G5 registra a decisão com controle de revisão e idempotência. É uma decisão local: não envia e-mail nem altera calendário.
- O runtime inicia quando a janela abre. Parar encerra o processo e o supervisor remove o socket da geração.
- Configurações diz se o banco é o estável ou um override de teste. A passphrase não aparece.

## Como executar

```bash
cd apps/api
uv sync --locked --python 3.12
cd ../desktop
npm ci
npm run tauri -- build --no-bundle
cd ../..
scripts/run-local-desktop.sh
```

O script pede a passphrase sintética no Terminal, sem eco e sem gravar. Se o terminal não for interativo, ele para. `JARVIS_DATABASE_PATH` é só override de teste; deixe-o indefinido para o banco estável.

Na janela: espere Pronto e canal Autenticado no protocolo 3. Abra a sessão em Missões com a mesma passphrase. Em Agora, grave uma ideia. Feche a janela e rode o script de novo: a ideia continua. Editar e Apagar ficam na mesma lista e também só no banco local. Em Runtime local, Parar deve voltar a Parado. A ideia não sai do Mac e não vai para um modelo.

## Persistência, migrações e recuperação

No macOS, o caminho diário padrão é `~/Library/Application Support/Jarvis/memory.sqlite3`. `JARVIS_DATABASE_PATH` é um override explícito e aparece como `override` em Configurações; mantenha-o indefinido para uso diário. O backend recusa banco dentro do repositório, link simbólico e diretório não privado; exige o diretório final `0700`, pertencente ao usuário, e mantém o arquivo SQLite em `0600`. `SQLiteMemoryStore.initialize()` aplica e valida as migrações versionadas antes de atender. A migração `0016_local_captures` cria uma tabela vazia, sem importar fixtures nem criar missão.

As ideias sobrevivem ao encerramento do processo e a uma nova sessão. A interface recarrega a lista do SQLite quando a sessão local abre. Erros de leitura/gravação mostram uma mensagem genérica e não incluem caminho, SQL ou conteúdo da ideia; uma falha de lista após gravação informa que a gravação já ocorreu para evitar repetição acidental. A API de captura chama apenas as funções SQLite de `local_captures`; não chama conectores, rede, classificador de missão ou modelo.

O repositório já tem exportação cifrada e restauração isolada via `backup_cli.py`. Com o runtime parado e `JARVIS_DATABASE_PATH` indefinido, use um terminal interativo:

```bash
cd apps/api
uv run --locked python backup_cli.py backup
uv run --locked python backup_cli.py restore jarvis-backup-v1-SEU_ID.jvb
```

O comando pede a senha sem eco ou argumento e grava o backup cifrado em `~/Library/Application Support/Jarvis/backups/`. A restauração autentica e valida o arquivo, integridade e esquema, e publica um novo banco em `~/Library/Application Support/Jarvis/restores/restore-v1-.../memory.sqlite3`; nunca substitui o banco diário. Automatizações e testes usam caminhos temporários, nunca o banco diário do proprietário.

## Roteiro do smoke manual

1. Deixe `JARVIS_DATABASE_PATH` indefinido e rode `scripts/run-local-desktop.sh`.
2. Espere Pronto, canal Autenticado, protocolo 3; em Configurações, confirme `stable`.
3. Em Missões, abra a sessão com uma credencial local sintética apropriada ao ambiente.
4. Em Agora, grave uma ideia sintética, edite-a e apague-a; confirme cada atualização na lista.
5. Grave outra ideia sintética, feche a janela/runtime, inicie novamente e abra a sessão. Confirme que a ideia persistiu.
6. Apague a ideia de smoke e confirme que nenhuma missão ou ação externa foi criada.
7. Em Runtime local, clique Parar até o estado Parado.

Os testes usam diretório temporário para CRUD, restart de processo, migração, falha de disco/permissão e backup/restauração. Não há smoke da janela registrado por esta implementação, nem fast-forward nesta fase.

## Matriz

| Funcionalidade | Evidência | Estado | Bloqueio | Próximo requisito |
|---|---|---|---|---|
| Captura de ideia | CRUD, restart de processo, migração `0016`, modos privados e erro de disco; testes no banco temporário | código/testes; smoke real da janela pendente | sessão local | o proprietário confirmar persistência visual após restart |
| Backup/restauração | CLI cifrada e restore isolado; testes temporários | código/testes | não há ativação automática do restore | validar somente se necessário, sem substituir o banco diário |
| Inbox | `/v1/app/connectors/status` | parcial | Gmail e Calendar não conectados | client ID e consentimento |
| Missões | rota nativa de leitura | pronto | concessão explícita | nenhum |
| Aprovações | grant explícito, um rascunho sintético opcional, leitura integral vinculada a revisão/SHA e aprovação no backend G5 | local sintético | sem ação externa; fila começa vazia e aceita um rascunho | consentimento de grant, confirmação do rascunho e confirmação do conteúdo/versão |
| Runtime | `start_on_launch` | pronto no checkout | sem pacote distribuível | nenhum para uso local |
| Configurações | `database_mode` `stable` ou `override` | pronto | passphrase não vai para Keychain | nenhum |
| Gmail e Google Calendar | `oauth_pkce.py`, PKCE S256, escopos só de leitura | não conectado | falta client ID e consentimento; nenhum listener TCP | cliente OAuth no Google Cloud |
| Calendar simulado | API do Gate D | sintético | não é conta Google | não tratar como integração real |

## Verificação desta candidata

Em 12/10/2026: `uv run --locked pytest -q test_daily_capture_gate.py test_native_app_api.py test_memory_store.py test_backup_recovery.py` — 96 passaram, zero ignorados; houve somente um aviso de depreciação do `starlette.testclient` com `httpx`. `node --test tests/runtimeCommand.test.mjs` — 9 passaram. `npm run tauri -- build --no-bundle` — passou; binário local em `apps/desktop/src-tauri/target/release/desktop`. `cargo fmt --all -- --check` e `git diff --check` — passaram. A janela não foi iniciada por estes testes; o smoke manual acima segue pendente.

## Google Cloud

1. Criar um cliente OAuth do tipo aplicativo para computador.
2. Cadastrar o redirect `jarvis://oauth/callback`.
3. Autorizar só `https://www.googleapis.com/auth/gmail.readonly` e `https://www.googleapis.com/auth/calendar.readonly`.
4. Exportar `JARVIS_GOOGLE_OAUTH_CLIENT_ID` no ambiente. Não colar o valor em documento, log ou commit.
5. O código só guarda um refresh token se houver consentimento explícito e um armazenamento injetado. A janela não grava no Keychain e não chama o Google.

## P3

| Risco | Disposição |
|---|---|
| `expires_at` divergir do instante numérico | Resolvido no cliente: os dois precisam coincidir. A tela usa o instante numérico. |
| Data sem fuso | Resolvido: o parser recusa instante sem deslocamento. |
| Concessão mostrada ativa até o ciclo de 500 ms | A tela deixa de mostrar ativa quando o instante já passou. O servidor continua autorizando. |
| Resposta perdida ao criar concessão | A repetição do mesmo escopo devolve a concessão existente, sem estender o prazo. |
| Launcher e passphrase | O script pede a passphrase sem gravar. O banco diário não depende de `JARVIS_DATABASE_PATH`. Distribuição segue bloqueada. |
| `source-map-js@1.2.1` | Permanece. Dependência transitiva de build. Lockfile não foi atualizado. |
| Processo do mesmo UID | Permanece. |
| Diretórios `.jv-*` vazios | Permanecem. |

## Atualização de confiança da aprovação — 12/10/2026

A revisão do estado anterior encontrou que uma chamada direta ao comando IPC podia enviar `confirmed: true` sem passar pelo checkbox do React. Na candidata isolada `feat/jarvis-g5-approval-native-consent`, baseada na candidata diária limpa `52917d5a5092174b35dd0d991043f61cfb71b0ec`, o comando não aceita esse campo. Antes de aprovar, o Rust consulta o detalhe pela rota fixa, mostra título, ID, revisão, SHA-256 e conteúdo marcado como não confiável num diálogo nativo, e só continua após a confirmação nativa. Cancelar não envia a decisão. A sessão, o grant e a versão continuam revalidados pelo backend G5 no momento da escrita; nenhuma rota ou URL vem do WebView.

O diálogo nativo usa `tauri-plugin-dialog`, dependência adicionada porque o checkbox do WebView não é uma fronteira de confiança. O corpo não contém tokens, passphrase ou segredos; os testes não iniciam uma janela. O smoke visual com a janela real e cancelamento/confirmação do diálogo continua pendente do proprietário.

O aceite histórico em `G6_MAC_002_2_MAC_003_ACEITE.md` não foi reescrito. Gmail e Calendar continuam desconectados. O smoke visual da jornada nova de Aprovações ainda precisa ser executado pelo proprietário.
