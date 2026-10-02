# G6-MAC-002 — Modelo de ameaças do transporte local

## Ativos

- capacidade aleatória da sessão (256 bits);
- associação de um endpoint a um child e a uma geração;
- integridade das respostas de versão e do probe;
- lifecycle de spawn, stop, reap e cleanup;
- estado que a WebView apresenta sem receber endpoint ou capacidade.

## Fronteiras e atores

| Ator | Capacidade presumida | Resultado esperado |
|---|---|---|
| WebView da aplicação | Invocar comandos Tauri registrados e ler estado tipado. | Não escolhe endereço nem recebe capacidade. |
| Runtime Manager | Criar sessão, spawnar/possuir child, entregar init pelo pipe, revogar e reap. | Fonte da associação endpoint → geração. |
| Child sintético supervisionado | Receber init pelo `stdin`, servir somente contrato sintético em UDS. | Deve provar a capacidade e compatibilidade. |
| Processo local falso | Pode abrir outro socket e imitar health/version; não possui capacidade da geração. | Falha na prova HMAC. |
| Outro Manager JARVIS | Possui seu child, path e capacidade próprios. | Provas entre sessões A/B são rejeitadas. |
| Outro usuário local | Não atravessa diretório 0700 nem socket 0600. | Não acessa o endpoint privado. |
| Mesmo usuário, administrador ou processo comprometido | Pode causar DoS e, dependendo de privilégios do host, inspecionar ou alterar processos/arquivos do mesmo usuário. | Fora da garantia criptográfica do ADR-010; HMAC não protege o host comprometido. |

## Abusos considerados

- Socket falso responde `200`, health correto e versão correta: prova com capacidade aleatória inválida é rejeitada.
- Replay de prova anterior: nonce aleatório fresco é parte do HMAC, portanto a resposta antiga não valida.
- Outra geração/Manager: ID e chave do runtime A são verificados contra a sessão A; B não valida A.
- Socket ausente, stale ou substituído: connect, versão/prova ou revogação falha fechado; sessão antiga nunca resolve endpoint da geração nova.
- Resposta inválida, excessiva, truncada, lenta, conexão fechada ou runtime que cai: limites e prazos geram `FAILED`; não há resposta infinita.
- UI tenta SSRF ou endpoint arbitrário: não existe comando genérico; comandos de transporte não recebem argumentos.
- Browser envia Origin: runtime sintético recusa header Origin. Browser não abre UDS através de fetch.
- Port scan/LAN: o transporte não cria listener TCP; endpoints de API web permanecem arquitetura separada e fora do cliente desktop MAC-002.

## Fora de escopo

Same-user malware com inspeção privilegiada, root/admin, exploração do próprio binário, revogação no nível do host contra administrador, FastAPI/G5/SQLite, contas, OAuth, rede externa/LAN, multiworker, assinatura/notarização e distribuição do `.app`.

## Controles observáveis

- segredo somente no pipe privado e memória native/child; nunca em args/env/URL/log/UI;
- path UDS efêmero por geração em diretório 0700, socket 0600;
- HMAC-SHA-256 com challenge CSPRNG, sistema Apple;
- Tauri commands tipados e CSP sem ampliação;
- estados separados de runtime e transporte;
- revogação no stop/crash; timeouts, limite HTTP e cleanup;
- logs com ID, tipo de endpoint, estado, versão e categoria; sem prova, chave ou corpo.
