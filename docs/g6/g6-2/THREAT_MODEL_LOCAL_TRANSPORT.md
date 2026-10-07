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
| Processo local falso | Pode abrir outro socket e imitar health/version/proof; não possui capacidade da geração. | A prova falsa falha; se substituir o socket após prova legítima, o PID do peer é recusado antes do primeiro byte da operação. |
| Outro Manager JARVIS | Possui seu child, path e capacidade próprios. | Provas entre sessões A/B são rejeitadas. |
| Outro usuário local | Não atravessa diretório 0700 nem socket 0600. | Não acessa o endpoint privado. |
| Processo do mesmo UID que renomeia/substitui o nome `.jv-*` | Pode trocar o path por symlink, arquivo, diretório ou socket e causar DoS. | O child valida identidade `dev`/`inode`; bind ocorre no CWD estabelecido pelo spawn; cleanup usa handle de diretório + `unlinkat`, sem seguir o parent mutável. Antes de cada operação, Rust valida `LOCAL_PEERPID`; pedidos/respostas G5 também têm confidencialidade e autenticação criptográfica por envelope v2. Canários fora da geração sobrevivem. |
| Mesmo usuário, administrador ou processo comprometido | Pode causar DoS e, dependendo de privilégios do host, inspecionar ou alterar processos/arquivos do mesmo usuário. | Fora da garantia criptográfica do ADR-010; HMAC não protege o host comprometido. |

## Abusos considerados

- Socket falso responde `200`, health correto e versão correta: prova com capacidade aleatória inválida é rejeitada.
- Replay de prova anterior: nonce aleatório fresco é parte do HMAC, portanto a resposta antiga não valida.
- Substituição depois da prova genuína: processo falso pode oferecer resposta HTTP, mas o PID do peer não corresponde ao child; Rust fecha antes de escrever cabeçalhos ou corpo. Mesmo que um relay transparente transporte bytes opacos, não consegue ler ou modificar o envelope G5.
- Cliente sem capability: texto claro em rotas G5 é recusado; envelope sem tag, com chave de outra geração ou com nonce repetido/antigo é recusado antes do dispatch.
- Resposta adulterada, envelope de outra geração ou nonce de resposta diferente do pedido: Rust não expõe o resultado ao Runtime Manager.
- Outra geração/Manager: ID e chave do runtime A são verificados contra a sessão A; B não valida A.
- Socket ausente, stale ou substituído: connect, versão/prova ou revogação falha fechado; sessão antiga nunca resolve endpoint da geração nova. Se o nome do diretório foi substituído, operações de cleanup continuam ancoradas no handle originalmente aberto e nunca percorrem o target do symlink.
- EOF permanente no pipe herdado: é perda de ownership. O child encerra em startup ou depois de READY; requests em andamento não publicam resposta tardia depois que o canal foi invalidado.
- Resposta inválida, excessiva, truncada, lenta, conexão fechada ou runtime que cai: limites e prazos geram `FAILED`; não há resposta infinita.
- UI tenta SSRF ou endpoint arbitrário: não existe comando genérico; comandos de transporte não recebem argumentos.
- Browser envia Origin: runtime sintético recusa header Origin. Browser não abre UDS através de fetch.
- Port scan/LAN: o transporte não cria listener TCP; endpoints de API web permanecem arquitetura separada e fora do cliente desktop MAC-002.

## Fora de escopo

Same-user malware com inspeção privilegiada, root/admin, exploração do próprio binário, revogação no nível do host contra administrador, FastAPI/G5/SQLite, contas, OAuth, rede externa/LAN, multiworker, assinatura/notarização e distribuição do `.app`.

## Controles observáveis

- segredo somente no pipe privado e memória native/child; nunca em args/env/URL/log/UI;
- path UDS aleatório por geração em diretório 0700 e socket 0600; aleatoriedade reduz colisões acidentais, não autoriza operações contra processos do mesmo UID;
- identidade `dev`/`inode` comparada e handle de diretório mantido pelo supervisor e child; `unlinkat` opera sobre o handle fixo e a folha `runtime.sock`, não sobre path absoluto mutável;
- prova HMAC-SHA-256 com challenge CSPRNG e envelope v2 AES-256-CTR + HMAC-SHA-256, com chaves separadas por direção/finalidade;
- verificação de PID via `LOCAL_PEERPID` em cada conexão, antes da escrita HTTP, com falha fechada;
- Tauri commands tipados e CSP sem ampliação;
- estados separados de runtime e transporte;
- revogação no stop, EOF e crash; timeouts, limite HTTP, cleanup ancorado ao handle e preservação de diretório vazio quando rmdir seguro não está disponível;
- logs com ID, tipo de endpoint, estado, versão e categoria; sem prova, chave ou corpo.

Veja a especificação e o resultado focado do MAC-002.2 em [MAC_002_2_ENCRYPTED_UDS.md](MAC_002_2_ENCRYPTED_UDS.md) e [MAC_002_2_REPORT.md](MAC_002_2_REPORT.md). A revisão de risco não cobre inspeção privilegiada da memória nem comprometimento do processo legítimo.
