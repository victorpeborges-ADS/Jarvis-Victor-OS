# Gate 2.0-B — Fundação local

Incremento de sessão e concessão. Não há SQLite, OAuth, conector Google nem dado real.

## Executar

Na pasta `apps/api`, com o ambiente Python 3.12 já usado no Gate 1:

```bash
source .venv/bin/activate
pytest -q
```

Para subir só em loopback, com uma frase local que não vai para o git:

```bash
JARVIS_LOCAL_PASSPHRASE='uma-frase-local-longa' python serve.py
```

O padrão de escuta é `127.0.0.1:8000`. Outro host é recusado. Sem a variável de ambiente, abrir sessão responde 503.

## Superfície

- `/events` e as demais rotas atuais continuam DEMO, sem sessão.
- `/real/session` abre e encerra a sessão local.
- `/real/grants` cria e revoga concessões de leitura.
- `/real/events` e `/real/briefing` devolvem só o catálogo sintético autorizado.

`domain_id` classifica o registro. A concessão diz se aquele principal pode lê-lo. Sem concessão ativa, a leitura responde 403. Sem sessão, responde 401.

## Pendências

Retenção, escopos OAuth e o destino dos eventos após revogação continuam sem aprovação. Esta etapa não cria cliente OAuth.
