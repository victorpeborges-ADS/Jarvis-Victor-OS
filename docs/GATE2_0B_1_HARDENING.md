# Gate 2.0-B.1 — Hardening da fundação local

**Base:** `feat/gate2.0-fundacao-local` @ `b916d4e`  
**Branch:** `feat/gate2.0-b1-hardening`  
**Escopo:** sessão, transporte local, concessões e tratamento de credenciais. Sem SQLite, OAuth, rede externa ou dados reais.

## Política implementada

- O comando suportado é `python serve.py`. Ele aceita somente `127.0.0.1` ou `::1` e desabilita proxy headers e access log do Uvicorn.
- A CLI direta do Uvicorn recusa a importação `main:app` e orienta usar o runner guardado. A camada ASGI também valida Host, peer e endereço local da conexão antes de encaminhar **qualquer** rota, inclusive DEMO, `/docs` e `/openapi.json`. Um runner alternativo com scope público recebe 403; Host não local recebe 400.
- Host aceito: `localhost`, IPv4 ou IPv6 loopback. Origens de navegador aceitas: `http://localhost:3000`, `http://127.0.0.1:3000`, `http://[::1]:3000`.
- Login e toda mutação `/real` exigem Origin permitido. Mutação exige ainda CSRF vinculado à sessão. Não existe fluxo de mutação sem Origin para clientes nativos.
- Grants são vinculados a principal, conector, recurso, conjunto de domínios canônicos, validade e estado de revogação. Só existe `calendar_sim`, só existe `calendar:synthetic-primary` e os domínios sintéticos são `dom_synthetic_a/b/c`.
- Grants ativos sobrepostos para qualquer tripla `(principal, connector, resource, domain)` são recusados com 409. Depois de revogar, o acesso efetivo daquele grant termina e um novo grant pode ser criado.
- Validade obrigatória: timestamp com fuso, no futuro, no máximo 30 dias. Agregação e busca direta por ID usam o mesmo autorizador. IDs fora do escopo retornam 404 para não revelar existência.
- Registros sem domínio, conector ou recurso canônico falham fechados.
- Rate limit: oito falhas numa janela de dez minutos iniciam cooldown de 60 segundos, com `Retry-After`. O bloqueio expira automaticamente. O estado é volátil e reinício o limpa; sessões antigas também falham fechadas após reinício.
- Erros de validação respondem mensagem genérica sem `input`; respostas `/real` e login usam `Cache-Control: no-store`.

## Matriz da auditoria anterior

| Achado B | Resultado | Evidência de correção |
|---|---|---|
| Host arbitrário / DNS rebinding potencial | Corrigido | `apps/api/loopback.py` valida Host literal; middleware global valida Host, peer e server scope. Testes de Host atacante e scope não local. |
| Login aceitava Origin externo ou ausente | Corrigido | `/real/session` exige Origin permitido antes de criar sessão. Testes externo e ausente retornam 403. |
| Mutação aceitava Origin ausente com CSRF válido | Corrigido | Toda rota mutável chama `_session_from(..., mutation=True)`, que exige Origin e CSRF. |
| Grant de Gmail autorizava catálogo Calendar | Corrigido | Autorizador compara conector, recurso e domínio em cada registro; Gmail não é conector canônico. Teste injeta grant interno inválido e obtém 403. |
| Domínio e conector desconhecidos aceitos | Corrigido | Literals/validadores de `GrantIn` recusam connector, resource e domain desconhecidos com 422. |
| Grant sem validade | Corrigido | `expires_at` obrigatório, timezone-aware, futuro e limitado a 30 dias. Teste de expiração bloqueia lista, briefing e ID direto. |
| Grants duplicados/overlapping sem política | Corrigido | Sobreposição ativa é negada com 409. Revogar o grant remove a permissão efetiva antes de nova concessão. |
| Lockout permanente após oito falhas | Corrigido | Cooldown de 60s com janela de 10min; testes verificam bloqueio, recuperação temporal e reinício. |
| Passphrase refletida em erros Pydantic | Corrigido | Handler de validação genérico; testes cobrem curta, longa, tipo errado e JSON truncado, incluindo `caplog`. |
| Uvicorn alternativo podia bindar publicamente | Mitigado e delimitado | Runner `serve.py` recusa bind público e desliga proxies. A CLI Uvicorn direta é recusada antes de subir. Middleware nega requests recebidos por interface pública em outros runners ASGI. |
| DEMO/docs potencialmente servidos por bind alternativo | Corrigido ao nível HTTP | Testes percorrem health, todas as rotas DEMO, docs, OpenAPI e sessão com scope público; todos retornam 403. |
| Sessão antiga depois de reinício | Corrigido/esperado | Sessões e grants são voláteis; subprocesso novo retorna 401 para cookie anterior. |

## Testes executados

| Suite | Resultado |
|---|---|
| pytest API (originais + B.1) | **35/35 PASS** |
| Vitest Gate 1 | **31/31 PASS** |
| Playwright Gate 1 desktop/mobile | **24/24 PASS** |
| Typecheck | PASS |
| ESLint via `npx next lint` | PASS, sem warnings; comando Next está deprecated para Next 16 |
| Build Next.js | PASS |

O `TestClient` emite o aviso conhecido de depreciação para a integração Starlette/httpx. Não afeta os resultados.

## Reprodução local

```bash
cd apps/api
source .venv/bin/activate
read -s 'JARVIS_LOCAL_PASSPHRASE?Passphrase local (mínimo 12 caracteres): '
export JARVIS_LOCAL_PASSPHRASE
python serve.py
```

O processo escuta em `127.0.0.1:8000` por padrão. Não execute com proxy reverso, túnel ou encaminhamento de porta. Não use `uvicorn main:app`; a CLI é recusada. Os endpoints DEMO continuam sem autenticação **no loopback**; o catálogo sintético `/real` exige sessão e grant. Não há suporte a mutações sem Origin.

## Riscos residuais e limites

1. Sessões, cooldown e grants ainda são apenas memória do processo. Reinício invalida sessões/grants e também reinicia o rate limit. Isso falha fechado para leitura, mas permite que o cooldown seja limpo reiniciando o processo. A persistência do rate limit depende de decisão para o incremento de banco; não usar contra atacante com acesso ao host.
2. A passphrase vem de variável de ambiente e é comparada em memória. Não existe hash adaptativo, keychain, rotação ou configuração visual. A proteção vale para protótipo local de usuário único, não para serviço remoto.
3. `serve.py` é o único runner suportado. A CLI Uvicorn é bloqueada, e ASGI requests por interface pública são recusados; um código Python deliberadamente customizado ainda pode abrir um socket público. O sistema operacional pode mostrar esse listener, embora o middleware recuse requests não locais. Nunca usar runner alternativo.
4. Origem HTTPS não está habilitada no desenho local; cookie `Secure` é usado quando a requisição chega por HTTPS, mas não há terminação TLS suportada.
5. Catálogo e domínios são estritamente sintéticos e pequenos. Ainda não há persistência, trilha de auditoria, limitação de grants por usuário em DB, backup nem sincronização.
6. O rate limit é por endereço de peer loopback, suficiente apenas para o proprietário único e runner suportado.

**Próximo passo:** auditoria independente deste commit. Somente depois dela poderá ser avaliado SQLite com registros exclusivamente sintéticos. OAuth continua sem autorização.
