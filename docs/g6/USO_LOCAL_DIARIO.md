# Uso local diário

Baseline da `main`: `21f1537e14706a42e8272f92cb4f4b6dab746640`.
Candidata anterior: `feat/jarvis-uso-local-diario` em `22f5decde620cbbe6d6e3017616e9e1b96961967`.
Esta branch: `feat/jarvis-uso-diario-mac`. Sem push, tag ou deploy.

O aplicativo continua em UDS, protocolo 3, com HMAC antes da descriptografia. Não há listener TCP, envio de e-mail ou criação de evento.

## O que dá para usar hoje

- Agora grava uma ideia de até 80 caracteres no SQLite. Sem `JARVIS_DATABASE_PATH`, o arquivo é `~/Library/Application Support/Jarvis/memory.sqlite3`, com diretório `0700` e sem fixtures.
- Inbox mostra runtime, canal UDS, Gmail, Google Calendar e o calendário simulado. Os dois primeiros conectores reais ficam não conectados.
- Missões lê só com `mission:read` explícito em `dom_synthetic_a`.
- Aprovações pede `mission:review` somente depois da confirmação `review-local`. Não concede sozinha e não executa ação externa. Sem revisão pendente, a fila fica vazia.
- O runtime inicia quando a janela abre. Parar encerra o processo e o supervisor remove o socket da geração.
- Configurações diz se o banco é o estável ou um override de teste. A passphrase não aparece.

## Como executar

```bash
cd /Users/vic/.codex/worktrees/jarvis-uso-diario-mac/Jarvis-Victor-OS/apps/api
uv sync --locked --python 3.12
cd ../desktop
npm ci
npm run tauri -- build --no-bundle
cd ../..
scripts/run-local-desktop.sh
```

O script pede a passphrase sintética no Terminal, sem eco e sem gravar. Se o terminal não for interativo, ele para. `JARVIS_DATABASE_PATH` é só override de teste; deixe-o indefinido para o banco estável.

Na janela: espere Pronto e canal Autenticado no protocolo 3. Abra a sessão em Missões com a mesma passphrase. Em Agora, grave uma ideia. Feche a janela e rode o script de novo: a ideia continua. Editar e Apagar ficam na mesma lista e também só no banco local. Em Runtime local, Parar deve voltar a Parado. A ideia não sai do Mac e não vai para um modelo.

## Roteiro do smoke manual

1. Deixe `JARVIS_DATABASE_PATH` indefinido.
2. Rode `scripts/run-local-desktop.sh` e digite uma passphrase sintética de 12 a 128 bytes.
3. Espere Pronto, canal Autenticado, protocolo 3.
4. Em Missões, abra a sessão com a mesma passphrase.
5. Em Agora, grave uma ideia. Feche e abra de novo. O texto deve continuar.
6. Se quiser, use Editar e Apagar. Nada disso é enviado para fora.
7. Em Runtime local, clique Parar até o estado Parado.

Os testes usam diretório temporário. Não há fast-forward nesta fase.

## Matriz

| Funcionalidade | Evidência | Estado | Bloqueio | Próximo requisito |
|---|---|---|---|---|
| Captura de ideia | gravação, edição, apagamento, restart e backup em banco temporário | sem smoke da janela | sessão local | o proprietário confirmar a persistência |
| Inbox | `/v1/app/connectors/status` | parcial | Gmail e Calendar não conectados | client ID e consentimento |
| Missões | rota nativa de leitura | pronto | concessão explícita | nenhum |
| Aprovações | rascunho sintético só com `confirm=draft-local` e concessão de revisão; aprovação só do item exibido | parcial | não há efeito externo; Gmail e Calendar continuam desligados | sua confirmação de cada passo |
| Runtime | `start_on_launch` | pronto no checkout | sem pacote distribuível | nenhum para uso local |
| Configurações | `database_mode` `stable` ou `override` | pronto | passphrase não vai para Keychain | nenhum |
| Gmail e Google Calendar | `oauth_pkce.py`, PKCE S256, escopos só de leitura | não conectado | falta client ID e consentimento; nenhum listener TCP | cliente OAuth no Google Cloud |
| Calendar simulado | API do Gate D | sintético | não é conta Google | não tratar como integração real |

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

O aceite histórico em `G6_MAC_002_2_MAC_003_ACEITE.md` não foi reescrito. Gmail e Calendar não estão conectados. Aprovar uma revisão local exige o checkbox daquele item; a janela não escolhe a rota.

## Handoff desta fase

- Base: `main` `21f1537e14706a42e8272f92cb4f4b6dab746640`.
- Partida: `feat/jarvis-uso-diario-mac` `3d3444dde9d25ab67426f1c5575063dc5652caed`.
- Worktree desta fase: `/Users/vic/.codex/worktrees/jarvis-rascunho-revisao/Jarvis-Victor-OS`, branch `feat/jarvis-rascunho-revisao`, a partir de `8953642`.
- Sem push, tag, deploy, fast-forward ou merge.
- A janela Tauri não foi aberta nesta fase. O binário release anterior não contém o rascunho.
- `source-map-js@1.2.1` permanece. Nenhuma dependência nova.
