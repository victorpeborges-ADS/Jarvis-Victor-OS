# Matriz de testes — G3

Ambiente: Mac mini 2018, Intel Core i5 de 6 núcleos, 32 GB. Uma instância de API por suíte. Capturas E2E em `/tmp/jarvis-g3-captures`, fora do git.

| Comando | Resultado |
|---|---|
| `uv sync --locked --python 3.12` em `apps/api` | PASS |
| `uv run --locked pytest -q` em `apps/api` | PASS — 157/157. Baseline histórica 149. Dois avisos de depreciação Starlette/httpx. Cerca de 20 s. |
| `npm ci` e `npm test` em `apps/web` | PASS — 64/64. Baseline histórica 63. Cerca de 5 s. |
| `npm run typecheck` | PASS |
| `npm run lint` | PASS. `next lint` avisa remoção no Next 16. |
| `npm run e2e` com `JARVIS_E2E_SCREENSHOT_DIR=/tmp/jarvis-g3-captures` | PASS — 36/36, desktop e mobile, cerca de 1,6 min. O build Next entra no runner. |
| Shells mobile e desktop | NÃO REEXECUTADOS. Nenhum arquivo desses apps mudou. |
| `git diff --check` no commit de teste `7460fd3` | PASS |
| `git diff --check fcca4eb..HEAD` | Ainda acusa o `gradlew.bat` em CRLF (94) e espaços finais anteriores à manutenção, porque `a6cd0ff` não foi integrado. |
| `git -c core.whitespace=cr-at-eol diff --check fcca4eb..HEAD` | Não acusa o CRLF. Continua acusando espaços finais reais pré-existentes em `build.gradle`, `GATE2_0E_ACEITE.md` e `STABILIZATION_REPORT.md`. |

## Probes

- Sem sessão no estado do Calendar: 401. Sem grant de leitura: 403. Com grant e nada classificado: 200 vazio.
- Inventário sozinho não lista catálogo nem eventos. Calendário de outro domínio fica oculto. Classificação fora do domínio: 403.
- GET com Origin permitido, sem Origin, Origin externo, `Sec-Fetch-Site: cross-site` e Host arbitrário.
- Grant `calendar_sim` não cria missão.
- Owner B não lê missão do owner A (404).
- Replay de idempotência não duplica; corpo diferente: 409.
- Revisão antiga: 409. Exceção depois de escrita na transação: 422 e revisão intacta.
- Reinício da API com o mesmo arquivo SQLite devolve a missão.
- Backup cifrado e restauração isolada devolvem `missions` e `mission_events`.
- Título com marcação é dado, não HTML executado. Texto de “instrução” permanece dentro do artefato determinístico.
- Importação repetida não duplica. JSON inválido fica em quarentena.
- Revogação do grant de leitura esconde a leitura seguinte com 403.
- E2E DEMO de missões continua sem chamar `/real/`.

## Limite do E2E

O Playwright não reinicia a API no meio do cenário. A parada e a nova leitura estão em `test_missions_api.py`. Isso não é E2E entre dispositivos.
