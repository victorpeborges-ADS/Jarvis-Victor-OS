# Segurança e residuais — G3

## Decisões

- `GET /real/calendar-sim/state` sem o recurso `calendar:synthetic-primary` responde 403. A interface não transforma isso em DEMO nem em catálogo vazio de sucesso.
- Descoberta de nomes não classificados exige `calendar:synthetic-inventory`. Esse recurso não autoriza sync nem eventos.
- Classificação de calendário sem domínio exige leitura do domínio alvo e inventário desse domínio.
- GET autenticado no loopback pode omitir `Origin`. Origin explícita fora da lista e `Sec-Fetch-Site: cross-site` respondem 403. Mutação continua com Origin permitido e CSRF. Host não loopback responde 400.
- Missões usam `mission_sim` / `mission:read` e `mission:write`. O campo `permission` do grant continua `read`; a capacidade está no recurso. Um grant de Calendar não entra nessa checagem.
- `domain_id` classifica a missão e o escopo do grant. Não autoriza sozinho.
- Artefato novo fica `draft`. Conhecimento derivado fica `staged`. Nenhum endpoint marca aprovação humana.
- A skill de captura é código determinístico. O título é dado, não instrução.

## Residuais

- Ausência de `Origin` em GET ainda não separa um cliente local de um pedido forjado no mesmo host. Não usar esta política para abrir a API fora de loopback.
- O login real continua com um único principal `owner`. A prova de dois owners usa `put_session_for_tests`, não um segundo login de produto.
- Não há worker durável. A etapa roda dentro do pedido. Não há resistência multiworker.
- O painel web lê e importa. Não executa as etapas no navegador; isso fica na API.
- A cópia DEMO no `localStorage` só é apagada se a pessoa marcar a opção e o servidor confirmar todos os itens enviados.
- O whitespace de `a6cd0ff` não faz parte desta branch.
- Backup cobre as tabelas novas porque o snapshot é o arquivo SQLite inteiro. Não houve teste de restore sobre o banco padrão do usuário.
