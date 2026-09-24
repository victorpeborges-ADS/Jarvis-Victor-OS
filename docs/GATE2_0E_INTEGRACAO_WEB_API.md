# JARVIS — Gate 2.0-E: integração web/API sintética

**Estado:** implementação concluída na branch `feat/gate2.0-e-integracao-web-api`; aguarda auditoria independente. Não aceita nem consolidada.

**Baseline:** `main` em `fcca4eb5e5a002d4ddd2f0f33997e74e1c8a3c72`, após o registro do aceite do Gate D. O Gate E começou nessa base.

## Objetivo e fronteiras

O modo **API local** conecta a interface Next.js à API já aprovada do Gate D/C.1, usando somente o catálogo Calendar fictício e um SQLite sintético local. O modo **DEMO** conserva as fixtures e o armazenamento demonstrativo do Gate 1. Os dois modos têm navegação e estado visual próprios; não há cópia de fixture DEMO para SQLite, nem consulta cruzada entre datasets.

O Gate E não cria credencial ou sessão automaticamente. A pessoa informa a frase local já configurada no backend; o backend decide a autenticação, a sessão e as concessões. A interface só permite criar uma concessão explícita de leitura `calendar_sim`, para um domínio sintético e com validade de sete dias. Os oito escopos da tela são rótulos sintéticos A–H; não representam autorizações institucionais nem alteram o papel de `domain_id` como classificação.

Não há OAuth, cliente Google, chamadas de rede externa, Gmail, Drive, LLM, ações externas, dados pessoais/institucionais ou deploy. Nenhuma migração SQLite foi necessária.

## Arquitetura

- `apps/web/lib/local-api.ts` contém os tipos de sessão, concessão, calendário, evento, estado e relatório. O cliente envia cookies com `credentials: include`, não armazena respostas em cache e converte HTTP 401/403/409/429 em mensagens seguras sem renderizar corpos internos.
- O hostname da API acompanha o hostname da página (`localhost` ou `127.0.0.1`) para que o cookie `SameSite=Lax` seja enviado. `NEXT_PUBLIC_JARVIS_API_URL` é uma opção de configuração, mas a validação rejeita host remoto, credenciais, path, query ou fragmento. A API fica na porta 8000.
- `apps/web/components/integration/LocalIntegrationProvider.tsx` mantém CSRF e dados protegidos somente na memória. Não usa `localStorage` ou `sessionStorage`; troca de modo limpa o estado protegido. Navegação de domínio invalida pedidos anteriores e limpa eventos. Uma resposta 401/403 aborta consultas pendentes e limpa eventos, estados, concessões e catálogo da interface.
- O cookie de sessão é emitido pelo backend como HttpOnly e SameSite=Lax. A UI recupera o CSRF após reload por `GET /real/session`, que exige cookie válido e Origin exata permitida, retorna `no-store` e não cria sessão. `GET /real/grants` também exige sessão e Origin exata e só lista grants ativos do principal.
- Classificação usa `PUT` com cookie, Origin e `X-CSRF-Token`; CORS aceita `PUT` apenas nas origens locais enumeradas pelo backend, sem wildcard com credenciais. O E2E Chromium completou essa requisição cross-origin e recebeu HTTP 200.
- `apps/web/app/integrado/page.tsx` apresenta grants, catálogo, classificação explícita, sincronização, estado da fonte e eventos autorizados. Eventos aparecem em ordem cronológica, com calendário, escopo e proveniência expansível. Esta tela não declara prioridade nem usa o motor de briefing DEMO.
- Estados são rotulados em português: não sincronizado, simulação atualizada, desatualizado e erro na sincronização. Erros não mostram payloads. Fonte e avisos deixam explícito que não há conta Google conectada.
- Em mobile, os controles recebem margem de rolagem para não ficarem sob o cabeçalho sticky ou a navegação fixa. O teste de regressão verifica CTA acima da barra inferior.

O runner E2E (`apps/web/scripts/run-e2e.mjs`) inicia `serve.py` em loopback, passa caminho e frase sintética exclusivos, cria banco sob diretório temporário, espera a API, executa Next em build/servidor de produção e remove somente o diretório que criou. Origens web/API de teste são validadas para HTTP loopback nas portas 3000/8000 e o runner rejeita hostnames diferentes antes de criar o banco. `apps/api/e2e_mark_calendar_state.py` é um utilitário exclusivamente E2E, restrito a `memory.sqlite3` dentro de um diretório direto do temp do sistema com prefixo do runner, usado para exercitar estado stale/error sem criar endpoint de produção.

## Execução local

Instale as versões fixadas e mantenha a frase local fora do repositório, do bundle e do histórico do shell. Inicie a API pelo runner suportado e abra a página e a API usando o mesmo nome de host local. O modo DEMO continua disponível sem API.

```bash
cd apps/api
uv sync --locked --python 3.12
# Configure JARVIS_LOCAL_PASSPHRASE no ambiente local privado, fora do repositório.
uv run --locked python serve.py
```

```bash
cd apps/web
npm ci
npm run dev
# Abra http://localhost:3000 e use a ação “API local”.
# Para o ambiente validado por E2E, abra http://127.0.0.1:3000.
```

O E2E deve ser executado pelo runner que cria o banco sintético e servidor isolado:

```bash
cd apps/web
npm run e2e
npm run e2e -- --project=desktop
npm run e2e -- --project=mobile
```

O runner pode ser exercitado também pelo hostname `localhost` (ambas as pontas ficam no mesmo site):

```bash
rtk env JARVIS_E2E_WEB_ORIGIN=http://localhost:3000 npm run e2e -- --project=desktop --project=mobile
```

## Testes executados

Resultados nesta implementação:

- `uv sync --locked --python 3.12`: PASS.
- `uv run --locked pytest -q` em `apps/api`, com `JARVIS_DATABASE_PATH` de guarda em `/tmp`: **138 passed**. Inclui regressões da sessão/Origin e coleção autorizada vazia; o banco padrão não foi inicializado.
- `npm ci`: PASS, instalação limpa; sem alterações de dependências ou lockfile.
- `npm run typecheck`: PASS.
- `npm run lint`: PASS; Next 15 informa que `next lint` será descontinuado no Next 16.
- `npm run build`: PASS; Next.js 15.5.26.
- `npm test -- --run`: **34 testes, 7 arquivos, PASS**.
- `npm run e2e -- --project=desktop --project=mobile`: **28/28 PASS**, em build novo, Next de produção e API em loopback com SQLite temporário. Abrange os testes Gate 1 e 1.3.2, além dos fluxos E. Os casos E exercitam sessão após reload, cookie expirado, logout, erro de login sem reflexão, classificação PUT real no browser, sync, proveniência, separação DEMO/API, stale/error, revogação durante resposta pendente e limpeza após 403.
- E2E direcionado com `JARVIS_E2E_WEB_ORIGIN=http://localhost:3000`: quatro casos desktop/mobile de integração e sessão passaram; confirma cookies e CORS quando ambos usam `localhost`.
- Configuração E2E com página em `localhost` e API em `127.0.0.1`: rejeitada antes de iniciar processos ou criar banco temporário.
- `npm audit` e `npm audit --omit=dev`: PASS, zero vulnerabilidades conhecidas.
- `pip-audit` foi aplicado ao export runtime de `uv.lock` (`uv export --locked --no-dev`): PASS, nenhuma vulnerabilidade conhecida.

O PUT cross-origin com `Content-Type` e `X-CSRF-Token` só chega à rota se o navegador aceitar o preflight CORS. O E2E observa a resposta 200 do PUT; os testes existentes da API seguem cobrindo o middleware e as rotas. Os testes usam seletores sem `force: true`.

## Capturas

As capturas são screenshots sintéticas criadas pelos testes nos projetos Playwright de 1280×800 e 390×844 (mobile usa escala física do dispositivo):

- [Integração com API — desktop](screenshots/gate2-e-integrado-desktop.png)
- [Integração com API — mobile](screenshots/gate2-e-integrado-mobile.png)
- [Modo DEMO — desktop](screenshots/gate2-e-demo-desktop.png)
- [Modo DEMO — mobile](screenshots/gate2-e-demo-mobile.png)

## Riscos residuais e limites de aceite

- A API continua exigindo o runner local e um único processo/worker. Sessões e grants permanecem voláteis; reiniciar o processo os invalida.
- A limitação do Gate D permanece: uma leitura GET que passou pela autorização antes de uma revogação pode terminar/respondê-la depois. A UI cancela consultas pendentes e limpa dados ao receber 401/403, mas isso não altera a semântica de autorização do servidor nem revoga bytes já recebidos.
- Em HTTP de loopback, o cookie não usa `Secure`; o limite depende de acesso local confiável ao dispositivo. Não expor o serviço à LAN ou à internet. O cookie é HttpOnly e SameSite=Lax; a frase de acesso nunca fica em localStorage e é limpa do formulário após o envio.
- `domain_id` e os escopos A–H não são autorização efetiva. A API valida sessão e grant por conector, recurso e domínio em toda leitura/escrita protegida.
- O provider continua fictício. Eventos de dia inteiro permanecem não suportados e exigem contrato antes de qualquer integração Calendar real.
- Um 403 causado por revogação limpa o estado protegido do navegador, mas o sistema não promete retirar conteúdo que já tenha sido renderizado ou observado fora dessa tela.
- As telas e provas E2E não autorizam armazenar dados pessoais, institucionais ou de saúde. OAuth, Google Calendar real, Gmail, Drive, LLM, retenção de dados reais e produção exigem decisões e aceite próprios.

## Próximo passo

Auditoria independente do Gate 2.0-E. Não fazer merge na `main` nem iniciar conectores reais antes do aceite humano/auditoria aplicável.
