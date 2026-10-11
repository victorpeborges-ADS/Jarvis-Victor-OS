# Uso local diário — matriz após MAC-002.2 / MAC-003

Baseline de partida: `main` local `21f1537e14706a42e8272f92cb4f4b6dab746640`.
Branch: `feat/jarvis-uso-local-diario`. Sem push, tag ou deploy.

O aplicativo macOS continua em UDS, protocolo 3, com HMAC antes da descriptografia. Esta rodada não abre listener TCP, não envia e-mail e não cria evento externo. Dados de teste são sintéticos.

## O que dá para usar hoje

Com o runtime local pronto, uma sessão aberta e a passphrase só no ambiente:

- Agora grava uma ideia de até 80 caracteres no SQLite do banco indicado. A ideia não vira missão.
- Inbox mostra o estado do runtime, do canal UDS, de Gmail, de Google Calendar e do calendário simulado.
- Missões mantém leitura só com concessão explícita `mission:read` em `dom_synthetic_a`.
- Aprovações não executa efeito externo. A fila de revisão do servidor continua exigindo `mission:review`, que este cliente não solicita.
- Runtime local inicia, mostra prontidão, para e oferece reinício após falha.
- Configurações mostra só opções que o processo realmente enxerga: passphrase presente ou ausente, banco indicado, `JARVIS_API_ROOT` e client ID OAuth presente ou ausente. Nenhum valor secreto é exibido.

## Como executar

O script não imprime a passphrase. O banco deve ficar fora do repositório.

```bash
cd apps/api
uv sync --locked --python 3.12
SCRATCH="$(mktemp -d)"
chmod 700 "$SCRATCH"
export JARVIS_DATABASE_PATH="$SCRATCH/synthetic.sqlite3"
export JARVIS_LOCAL_PASSPHRASE   # defina no shell; não grave no git
uv run --locked python -c "from memory_store import SQLiteMemoryStore; from mission_repository import MissionRepository; import os; store=SQLiteMemoryStore(os.environ['JARVIS_DATABASE_PATH']); store.initialize(); MissionRepository(store).create('owner', 'Missão sintética local', 'dom_synthetic_a', 'uso-local-seed')"
cd ../desktop
npm install
npm run tauri -- build --no-bundle
cd ../..
scripts/run-local-desktop.sh
```

Na janela: Iniciar, esperar Pronto e canal Autenticado no protocolo 3, abrir a sessão em Missões e gravar a ideia em Agora.

## Matriz

| Funcionalidade | Evidência | Estado | Bloqueio | Próximo requisito |
|---|---|---|---|---|
| Captura de ideia | `local_captures` + `/v1/app/captures/*` | pronto no banco sintético | sessão local | nada para o uso sintético |
| Inbox de fontes | `/v1/app/connectors/status` | parcial | Gmail e Calendar real não conectados | client ID e consentimento |
| Missões | rota nativa já aceita | pronto para leitura autorizada | concessão explícita | sem mudança de escopo |
| Aprovações | UI sem efeito externo | parcial | falta `mission:review` neste cliente | decisão do proprietário antes de conceder revisão |
| Runtime | supervisor existente | pronto no checkout | sem pacote distribuível | instalador, se for autorizado |
| Configurações | `runtime_local_config` | pronto para o que existe | sem Keychain | não guardar passphrase em arquivo |
| Gmail leitura | `external_connectors.py` | não conectada | client ID ou consentimento | escopo `gmail.readonly`; nenhum envio |
| Google Calendar leitura | mesmo módulo | não conectada | client ID ou consentimento | escopo `calendar.readonly`; nenhuma escrita |
| Calendar simulado | API já aceita no Gate D | sintético, não ligado a esta janela | não é conta Google | não tratar como integração real |

## OAuth que ainda depende do proprietário

Não há client ID no repositório e esta rodada não abre navegador nem troca código. Para uma próxima etapa, ainda sem escrita:

1. Criar um cliente OAuth desktop no Google Cloud, só com os escopos `https://www.googleapis.com/auth/gmail.readonly` e `https://www.googleapis.com/auth/calendar.readonly`.
2. Exportar `JARVIS_GOOGLE_OAUTH_CLIENT_ID` no ambiente. Não colar o valor em documento, log ou commit. O segredo de cliente, se existir, também fica só no ambiente.
3. O aplicativo passará a dizer “consentimento ainda não dado”. A leitura real só deve começar depois de um consentimento explícito separado. Enviar e-mail ou alterar evento continua fora.

Enquanto o client ID não existir, Gmail e Google Calendar ficam **não conectados**. O calendário simulado continua sendo dado sintético.

## P3

| Risco | Disposição nesta branch |
|---|---|
| `expires_at` divergir de `expires_at_epoch_us` | Resolvido no cliente Rust: os dois precisam ser o mesmo instante. A tela usa o instante numérico. |
| Data sem fuso | Resolvido no parser Rust: instante sem deslocamento é recusado. |
| Concessão ativa até o ciclo de 500 ms | A tela deixa de mostrar ativa quando o instante do servidor já passou, sem esperar o próximo ciclo. O servidor continua sendo a autorização. |
| Resposta perdida ao criar concessão | A repetição do mesmo escopo devolve a concessão existente e não estende o prazo. Sobreposição diferente continua conflito. |
| Launcher por `CARGO_MANIFEST_DIR` e passphrase no ambiente | `JARVIS_API_ROOT` escolhe o diretório com `serve.py`. A passphrase continua só no ambiente e não é gravada. Distribuição segue bloqueada: sem instalador, Keychain ou runner embutido. |
| `source-map-js@1.2.1` | Permanece. É dependência transitiva de build, em `apps/desktop` e `apps/web`. Não houve atualização de lockfile. |
| Processo do mesmo UID | Permanece. O modelo local não muda. |
| Diretórios `.jv-*` vazios | Permanece. A retenção não remove diretório por pathname mutável. |

O registro histórico em `G6_MAC_002_2_MAC_003_ACEITE.md` não foi reescrito. Os itens acima que continuam abertos também continuam impedindo qualquer declaração de produto distribuível.
