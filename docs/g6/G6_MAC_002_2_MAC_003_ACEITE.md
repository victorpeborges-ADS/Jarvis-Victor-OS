# Aceite local — G6 MAC-002.2 e MAC-003

## Decisão

O proprietário confirmou a jornada real na janela Tauri e autorizou o fechamento local. A candidata funcional auditada é `4bd65d3fb53256141a5067ec40c47b3778e22efa`, na branch `feat/jarvis-g6-final-response-barrier`, descendente da `main` `bf575be1645578eebedd41cddd3463b75726776b`.

Este arquivo é o commit documental de aceite. Não altera runtime, formato v3, lockfiles nem código. A integração local é fast-forward da branch candidata, já com este registro, sobre essa `main`. Não há push, tag ou deploy.

O smoke não foi uma automação independente. A tentativa do agente parou porque `System Events` respondeu `UI elements enabled = false`. O proprietário executou a janela e relatou o resultado.

## Jornada confirmada pelo proprietário

- Janela Tauri real aberta.
- Runtime **Pronto**, canal **Autenticado**, protocolo 3.
- Sessão local aberta.
- Consentimento explícito e concessão `mission:read` em `dom_synthetic_a`.
- Missão **Missão sintética MAC-003** exibida.
- Concessão revogada e leitura negada.
- Sessão encerrada e reaberta sem herdar concessão; leitura novamente negada.
- Sessão encerrada e runtime parado.

Nenhuma passphrase, token ou caminho de socket entra neste registro. A negativa vista no botão da janela é a frase do cache Rust. A negativa do FastAPI depois da revogação permanece a evidência do teste `production_launcher_supervises_real_fastapi_g5_stop_eof_crash_and_restart`.

## Escopo aceito

- Envelope v3 com partição de contador por mensagem, HMAC antes do CTR e reserva monotônica de sequência.
- Desativação que espera a transação G5, inclusive o intervalo depois da leitura e antes da abertura da resposta. O gancho `received`/`opened` existe só em teste.
- Supervisor de produção com FastAPI real sobre UDS, sessão, concessão, revogação, STOP, EOF, crash e restart.
- Jornada manual da WebView no escopo sintético acima.

## P3 fechados neste marco

Estes itens deixam de ser residuais. Ficam citados para não serem relidos como pendências:

- Replay autenticado reservado antes do AES-CTR, em `2cd1661`.
- Sequência estacionada em `u64::MAX` junto com a destruição do segredo, em `2cd1661`.
- Envio em curso concluído antes de `deactivate` retornar, com barreiras `admitted`, `sealed`, `checked` e `received`, até `4bd65d3`.

## P3 deferidos

Aceitos como limites deste marco local. Nenhum foi corrigido neste commit. Nenhum autoriza distribuição.

| Risco | Disposição |
|---|---|
| Expiração: Rust exige `expires_at_epoch_us` e trata `expires_at` como texto de exibição, que pode divergir do ISO | Deferido. O FastAPI atual continua autoritativo. Consistência do DTO fica para antes de ampliar consumidores. |
| String de data sem validação de fuso no parser Rust | Deferido. A API atual emite datas UTC com fuso e rejeita datetime sem fuso. Exigir o mesmo no DTO antes de distribuição. |
| A interface pode mostrar concessão ativa até o próximo ciclo de cerca de 500 ms | Deferido. É atraso visual. Rust e servidor não estendem a autorização. |
| Resposta de criação da concessão perdida, com possível `grant_conflict` na repetição | Deferido. Fechar a sessão invalida a concessão. Recuperação idempotente fica para uso mais amplo. |
| Launcher de release resolve `serve.py` por `CARGO_MANIFEST_DIR` e só repassa a passphrase se ela já estiver no ambiente | Deferido e **bloqueia distribuição**. Não há instalador, Keychain nem runner embutido. |
| Advisory `source-map-js@1.2.1` (`GHSA-68fv-2mgg-jv7q` / CVE-2026-93749), transitivo de Vite/PostCSS | Deferido. Dívida de build/dev, a resolver antes de distribuição. Lockfiles não foram alterados. |
| Processo local do mesmo UID pode observar paths, causar negação de serviço ou agir como host comprometido | Deferido como limite do modelo local. A substituição de socket é recusada por `LOCAL_PEERPID` antes de bytes HTTP; isso não cobre root, SIGKILL nem inspeção de memória. |
| Diretórios `.jv-*` vazios podem permanecer no temporário | Deferido. A retenção evita remover um diretório por pathname mutável. |

## Fora deste aceite

O marco local não torna o projeto pronto para distribuição. Continuam fora: empacotamento, notarização, OAuth, Calendar real, Gmail, Drive, dados pessoais ou institucionais, acesso remoto e deploy.
