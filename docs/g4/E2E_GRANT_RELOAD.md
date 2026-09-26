# Oscilação do E2E mobile na volta do DEMO

A auditoria do `05881e033e8aaa1cddd8ea4353c86207146bc22c` viu, numa suíte completa, a sessão ativa e as concessões ausentes em `integration.spec.ts:139`. A repetição isolada passou. A causa está na interface.

## Causa

`refreshEvents` chamava `cancelPending()` antes de saber se já havia concessão. No mobile, o teste seleciona o escopo B assim que o título "Concessões locais" aparece. Esse título depende só da sessão. A seleção dispara `selectDomain` enquanto o `GET /real/grants` da volta do DEMO ainda está em voo. O cancelamento global aborta essa resposta. O carregamento termina sem gravar as concessões e sem nova tentativa. A sessão permanece autenticada e a agenda fica vazia.

No desktop o filtro já está no escopo A, então o teste não troca o domínio nessa janela. Os projetos E2E usam `workers: 1` e não rodam ao mesmo tempo. O backend conservava as concessões: depois da tela vazia, a revogação ainda encontrava os registros.

No trace da reprodução, o `GET /real/grants` aberto na volta ficou com `time: -1` e `status: -1`. Os GET anteriores da mesma sessão tinham status 200.

## Correção

A leitura de eventos deixa de abortar o carregamento de concessões, catálogo e estados. Uma leitura mais nova ignora a resposta antiga por um contador próprio. Trocar o escopo durante o carregamento não apaga a sessão nem as concessões já concedidas.

## Resultados nesta worktree

- Reprodução com atraso de 1,2 s no `GET /real/grants`, antes da correção: a asserção da concessão falhou e a tela mostrou sessão ativa sem concessão.
- A mesma reprodução, três vezes seguidas no mobile, depois da correção: 3/3.
- Duas suítes completas consecutivas, desktop e mobile: 40/40 e 40/40, exit 0.
- `test_cancel_confirmed_before_skill_prevents_artifact` e `test_revoked_write_grant_before_commit_requires_new_grant_to_resume`: 2/2.
- `npm run typecheck` e `npm run lint`: exit 0.

## Residual

Uma leitura de eventos mais lenta pode terminar depois de outra mais nova; o contador impede que ela substitua a lista vigente. Isso não cancela o carregamento das concessões. A suíte continua com um worker e um processo de API.
