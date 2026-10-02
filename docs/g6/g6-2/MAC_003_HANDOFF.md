# Handoff técnico — MAC-003 / FastAPI sem trocar o transporte

Este roteiro não executa, importa nem autoriza a API nesta candidata. MAC-003 precisa de autorização e gate próprios antes de qualquer alteração em `apps/api`, abertura de SQLite ou migração.

## Contrato de fio preservado

O native client continua conectando ao UDS da geração capturada e enviando HTTP/1.1 com `Host: jarvis.local`, timeout e limites explícitos. O contrato sintético atual é:

1. `GET /v1/health` → body `ok\n` (somente prontidão, sem autenticação).
2. `GET /v1/version` → campos `protocol_version`, `runtime_kind`, `instance_id`, `build` (somente compatibilidade, sem autenticação).
3. `POST /v1/instance-proof` → body com nonce hex de 32 bytes; resposta inclui `protocol_version`, `runtime_kind`, `instance_id`, `build`, `operation_result` e `proof`. `proof` é HMAC-SHA-256 sobre domínio, identidade, versão, nonce e resultado.

O wire format HTTP, rotas, política de tamanho, Host, UDS e segregação de segredo permanecem iguais. MAC-003 deve revisar a allowlist de `runtime_kind`/build para a versão aprovada do FastAPI; nunca aceitar versão desconhecida por fallback. Se a revisão exigir mudar framing, campos ou segurança do proof, elevar `protocol_version` e documentar a migração.

## Trabalho necessário em MAC-003

1. Preservar `Runtime Manager` como owner de spawn, PID, geração, endpoint privado, stop/restart, timeout e reap. Nenhum endpoint chega à WebView.
2. Trocar o helper sintético por um processo Python local supervisionado, sem alterar o cliente Tauri/React para URL, porta ou fetch.
3. Adaptar o runner oficial `apps/api/serve.py`, hoje bindado a loopback TCP, para aceitar UDS com o path criado pelo parent. Uvicorn oferece configuração `uds`; verificar também permissões do socket no runtime-alvo. Referências: [Uvicorn settings](https://www.uvicorn.org/settings/) e [Uvicorn deployment](https://www.uvicorn.org/deployment/).
4. Ler o registro de inicialização de `stdin` antes de iniciar Uvicorn; não pôr chave em argv, environment, URL ou log. Expor a capacidade em contexto privado de processo à rota de prova e usar `hmac`/`hashlib` da biblioteca padrão Python ou biblioteca já aprovada. Conferir nonce, tamanho e comparação segura.
5. Implementar as mesmas rotas sintéticas e o proof antes de ligar domínio de produto. `health` continua separado da prova.
6. Somente no escopo autorizado, integrar app FastAPI real, SQLite/G5 e startup sem bypass de `serve.py`; executar migrations conforme ADR-010 e as autorizações vigentes. Não ativar multiworker.
7. Provar com teste de processo que o UDS não abre TCP; repetir fake runtime, versões antigas, cross-manager, stale endpoint/generation, crash/request, stop/reap e todas as corridas MAC-001.
8. Revisar limites HTTP conforme contrato real; nunca ilimitados. Preservar CORS fechado no UDS e recusar Origin; não ampliar CSP.

## Compatibilidade real observada

O runner atual `apps/api/serve.py` chama `uvicorn.run(create_app(config), host=config.host, port=config.port, proxy_headers=False, ...)`; não recebe UDS nesta branch e seu startup prepara o store. A documentação oficial do Uvicorn confirma opção UDS, mas não prova a compatibilidade nem a segurança da futura aplicação. MAC-003 precisa implementar e testar a adaptação, sem assumir que o servidor atual já a oferece.
