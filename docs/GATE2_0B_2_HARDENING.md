# Gate 2.0-B.2 — Encerramento dos bloqueadores da fundação local

**Base:** `feat/gate2.0-b1-hardening` @ `3517364`  
**Branch:** `feat/gate2.0-b2-local-startup-lock`  
**Escopo:** inicialização local e lock Python 3.12. Sem SQLite, OAuth, contas reais ou serviços externos.

## Política de inicialização

- `apps/api/main.py` não exporta mais um objeto global `app`. A API é criada por `create_app(config: LocalServerConfig)`, que exige configuração explícita.
- `LocalServerConfig` aceita somente `127.0.0.1` ou `::1` e valida a porta. O lifespan revalida a configuração antes de iniciar.
- `python serve.py` é o único entrypoint suportado. Ele valida a configuração e passa a instância da aplicação ao Uvicorn com proxy headers desabilitados, lista de proxies confiáveis vazia e access log desligado.
- `python -m uvicorn main:app ...` e `uvicorn.run("main:app", ...)` falham ao resolver a aplicação, antes de iniciar o listener. `uvicorn main:create_app --factory ...` falha porque a factory exige configuração.
- A fronteira ASGI ainda confere Host, endereço do peer e endereço local da conexão em cada requisição. TestClient usa a mesma factory e configuração local, sem modo de autenticação especial para testes.

### Evidência em sockets reais

Os testes subprocess usam portas livres e abrem sockets; não simulam o transporte com TestClient.

| Cenário | Resultado observado |
|---|---|
| `python serve.py`, conexão em `127.0.0.1` | `/health`, `/events`, `/docs` e `/openapi.json` retornam 200; `/real/events` retorna 401 sem sessão. |
| `python serve.py`, conexão pelo IPv4 LAN | Conexão recusada: não há listener nessa interface. |
| `python -m uvicorn main:app --host 0.0.0.0` | Processo termina antes de escutar; a porta não aceita conexão. |
| `uvicorn.run("main:app", host="0.0.0.0", ...)` | Processo termina antes de escutar; a porta não aceita conexão. |
| `uvicorn main:create_app --factory` sem configuração | Falha antes de escutar; a porta não aceita conexão. |
| Programa customizado cria app com config loopback e a vincula a `0.0.0.0` | Demonstra o limite da confiança: o processo arbitrário consegue abrir listener. Requisições pela interface LAN retornam 403 para DEMO, `/docs`, OpenAPI e `/real`; loopback ainda recebe as rotas locais. |

O JARVIS não pode impedir que o próprio proprietário execute código Python arbitrário e abra um socket. A garantia implementada cobre o launcher oficial, as formas usuais de importação do Uvicorn e a recusa de tráfego não loopback na camada ASGI; não é uma sandbox do processo nem do usuário do sistema.

**Proteções complementares no Mac:** manter o Firewall do macOS ativo e negar conexões de entrada para processos Python/Uvicorn; não criar regras PF, encaminhamento no roteador, túnel ou proxy reverso; limitar o uso ao usuário local e manter FileVault ativo. Essas medidas não substituem o launcher e precisam ser conferidas no host antes de qualquer dado pessoal.

## Lock Python

- `apps/api/pyproject.toml` declara Python `>=3.12,<3.13`, dependências de runtime e grupo de desenvolvimento.
- `apps/api/.python-version` seleciona Python 3.12.
- `apps/api/uv.lock` fixa as dependências transitivas, versões, markers e hashes. Gerado com `uv 0.12.13` no Mac Intel (`x86_64-apple-darwin`).
- `requirements.txt` permanece como lista legada de dependências diretas; `uv.lock` é a fonte canônica para instalação reproduzível.

Instalação e testes no Mac Intel:

```bash
cd apps/api
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked pytest -q
```

`uv sync --locked` falha se `pyproject.toml` e `uv.lock` divergirem. Para auditar somente o runtime travado, exporte-o e execute `pip-audit` em ambiente isolado da ferramenta:

```bash
uv export --locked --no-dev --format requirements.txt --output-file /tmp/jarvis-api-runtime-lock.txt
uvx --from pip-audit pip-audit -r /tmp/jarvis-api-runtime-lock.txt
```

O `uvx` mantém o scanner separado dos pacotes da aplicação; o arquivo exportado inclui as versões runtime fixas do `uv.lock`.

## Resultados

| Verificação | Resultado |
|---|---|
| pytest API, instalação nova com Python 3.12.14 + `uv.lock` | **39/39 PASS** |
| Novos testes de sockets e entrypoints | **4 PASS** dentro dos 39; LAN negada ou sem listener conforme o cenário. |
| `pip-audit` sobre export runtime do lock | **Nenhuma vulnerabilidade conhecida**. O scanner executou via `uvx` e não foi incluído no inventário da aplicação. |
| Vitest | **31/31 PASS** |
| Playwright desktop/mobile | **24/24 PASS** |
| Typecheck, lint e build Next.js | **PASS** |
| `npm audit` e `npm audit --omit=dev` | **0 vulnerabilidades** |

O pytest informa dois avisos de depreciação em Starlette/httpx TestClient; não houve falha. As verificações frontend foram feitas em `npm ci` limpo, numa cópia temporária, sem alterações no estado original do Gate 1.

## Limites e pendências

1. Código executado pelo próprio proprietário pode ignorar `serve.py`, criar outro servidor e abrir sockets. A aplicação barra peers externos quando esses requests passam pela factory/middleware JARVIS, mas não controla listeners que sirvam outra aplicação nem substitui firewall do sistema.
2. Um programa customizado pode construir a app com configuração loopback e depois vincular o Uvicorn a uma interface pública. Os probes confirmam que o middleware bloqueia os requests LAN testados, mas o listener existe. Evitar executar código customizado e usar as proteções de firewall descritas acima.
3. `serve.py` é o único caminho operacional aprovado. Não usar proxy reverso, túnel ou port forwarding.
4. A passphrase continua em variável de ambiente, sessões/grants/rate limit seguem voláteis e o modo local ainda usa HTTP. Esses itens impedem conexão com contas reais e não foram ampliados nesta etapa.
5. SQLite, OAuth, integrações externas, dados reais e Gate 2.0-C continuam fora do escopo e dependem de auditoria e aprovação posteriores.

**Próximo passo:** auditoria independente da branch B.2. Esta entrega não autoriza SQLite ou OAuth.
