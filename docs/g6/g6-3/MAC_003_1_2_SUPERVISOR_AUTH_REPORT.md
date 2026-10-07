# MAC-003.1.2 — Supervisor e autenticação

Data: 07/10/2026, America/Sao_Paulo. Relatório de implementação e auditoria focada; não constitui aceite formal.

## Baseline e isolamento

- Base exata: `059871ff7e753bc4e785d77d5f209c6ebef33d71`.
- Branch isolada: `feat/jarvis-g6-mac-003-1-2-supervisor-auth`.
- Main esperada e preservada: `bf575be1645578eebedd41cddd3463b75726776b`.
- Worktree: `/Users/vic/.codex/worktrees/jarvis-mac-003-1-2-supervisor-auth/Jarvis-Victor-OS`.
- O checkout compartilhado permaneceu em `feat/gate2.0-e-integracao-web-api`; seus quatro arquivos untracked iniciais foram preservados. A candidata anterior permaneceu limpa em seu SHA original. Nenhuma outra worktree foi editada.
- `git diff --check` e ancestralidade desde a base passaram.

## P2 do supervisor: reproduzido como lacuna de teste; caminho de produção PASS

O teste já citado no handoff, `rust_manager_uses_fastapi_g5_over_authenticated_uds`, é um teste unitário dentro de `runtime_manager.rs`. A leitura do corpo do teste confirma que ele cria `serve.py` com `Command` diretamente, escreve o registro de init e o ACK, lê READY manualmente e injeta `RuntimeSnapshot`, `TransportSnapshot` e `TransportSession` dentro do manager. Ele exercita G5 e a prova, mas não executa o spawn/READY/ACK/reap do supervisor de produção. O nome não era evidência suficiente; o corpo mostrou o bypass.

Foi acrescentado `mac003_production_supervisor`, um alvo Cargo de integração. O alvo importa `desktop_lib` como dependência normal com a feature `mac003-production-supervisor-test`. Na compilação verbosa, a linha de `rustc --crate-name desktop_lib` produz `rlib` sem `--test` nem `--cfg test`; a linha seguinte compila o arquivo de integração com `--test` e `--extern desktop_lib=...rlib`. Portanto o `#[cfg(not(test))]` de `helper_command` fica ativo na biblioteca e seleciona o caminho de produção baseado em `CARGO_MANIFEST_DIR/../../api` e `serve.py`. O runner não constrói READY, ACK ou transporte: `RuntimeManager` cria o child, lê READY, escreve ACK, valida o HMAC, supervisiona e recolhe o próprio child.

O alvo usa apenas passphrase, missão e banco sintéticos. Ele verificou:

1. FastAPI real iniciado pelo `RuntimeManager`; READY e `TransportState::Ready` só depois da prova autenticada.
2. Abertura de sessão, concessão explícita, listagem da missão `api_synthetic`, revogação e negativa no cache Rust. Uma sonda de integração envia a leitura ao FastAPI depois da revogação, ignorando o bloqueio local; o próprio servidor responde `grant_required` (exposto pelo DTO Rust como “concessão de leitura ausente ou expirada”).
3. Fechar e reabrir sessão limpa o grant; a nova sessão inicia sem autorização.
4. STOP pelo manager termina com código 0; o child já foi reapado quando `stop_and_wait` retorna e o socket foi removido pelo cleanup ancorado ao diretório da geração.
5. Fechar o canal de controle pelo supervisor faz o FastAPI observar EOF, sair com código 48 e terminar em `STOPPED/supervisor_lost`; o manager reapou o child e limpou o UDS.
6. Um gatilho restrito à feature de teste provoca crash no child a partir do worker supervisor. O manager observa e reap o child como `CRASHED/child_crash`; `restart_runtime` cria outra geração, autentica READY e encerra por STOP normal.

O teste terminou com `1 passed; 0 failed`, em 4,38 s. Saídas seguras do alvo:

```text
production_supervisor stage=ready_g5_grant_read_revoke PASS
production_supervisor stage=STOP_reap_uds_cleanup PASS
production_supervisor stage=EOF_supervisor_lost_reap_cleanup PASS
production_supervisor stage=crash_reap PASS
production_supervisor stage=restart_READY_STOP_reap_cleanup PASS
```

Conclusão: a lacuna do handoff estava confirmada; a implementação atual do caminho de produção passou pela jornada de supervisor real e a lacuna foi coberta por regressão. Não houve alteração da implementação do handshake MAC-002. A integração usa os métodos do `RuntimeManager`, não a janela Tauri nem o invoke IPC; isso não fecha o P2 da WebView.

## MAC-002: direção da prova e chamadas recebidas pelo UDS

`native_runtime.py` guarda a capability no processo FastAPI e produz HMAC-SHA-256 de identidade, versão, nonce e resultado em `/v1/instance-proof`. `transport.rs` gera nonce novo, valida a resposta com a capability e só então marca o runtime autenticado. Isso prova **o servidor para o cliente Rust**. A rota não pede prova ao chamador e responde a nonce sintético de qualquer peer que alcance o socket.

O servidor não autentica cada conexão de aplicação com a capability MAC-002. `NativeProtocolBoundary` restringe framing, headers, método, rotas e readiness, mas não valida uma MAC por chamada. O `TransportSession` faz o probe antes de cada operação, porém a prova e a operação usam conexões UDS separadas. A API aplica controles próprios:

| Operação | Controle do servidor observado |
|---|---|
| `health`, `version`, `instance-proof` | Sem passphrase, sessão ou grant. A prova é uma resposta assinada pelo servidor, não autenticação do peer. |
| Abrir sessão | Passphrase local e rate limit. |
| Fechar sessão | Token de sessão e CSRF válido. |
| Criar/revogar grant | Sessão e CSRF; domínio/recurso são allowlist fixa. |
| Listar missão | Sessão ativa e grant `mission:read` correspondente à sessão e ao domínio. |

Uma segunda aplicação/processo sob o mesmo UID conectou-se ao UDS sintético sem capability e sem enviar prova HMAC. A sonda, executada em subprocesso do mesmo usuário e sem imprimir corpos, tokens ou provas, obteve:

```text
health=200;version=200;proof=200;open=credential_rejected;close=session_required;grant=session_required;revoke=session_required;read=session_required
```

Assim, um peer local do mesmo UID consegue acessar o socket e os endpoints de controle. Sem a passphrase, sessão, CSRF e grant correspondentes, a leitura de missão foi recusada. O servidor não exige prova de cliente por requisição; a autorização de produto está nas rotas G5.

Há uma diferença de redação a decidir antes de afirmar autenticação mútua: `RUNTIME_AUTHENTICITY.md` descreve corretamente Rust validando HMAC do helper, mas `TRANSPORT_DECISION.md` diz que “clientes locais ainda precisam da prova HMAC”, frase que pode ser entendida como prova de cliente exigida pelo servidor. “UDS autenticado” também pode ocultar essa direção. A menor decisão é confirmar formalmente MAC-002 como autenticação do runtime para Rust e esclarecer que chamadas recebidas dependem de autenticação G5, com acesso ao UDS permitido ao mesmo UID. Se a intenção era autenticação mútua, isso requer decisão MAC-002.2, versão e prova de requisição vinculada a método, rota, corpo e proteção contra replay. Não alterei contrato, handshake, versão nem documentação canônica nesta rodada.

O probe não tentou interceptar um corpo G5. Pela inspeção, prova e chamada de aplicação conectam separadamente ao pathname do socket; em tese, um processo com o mesmo UID que substitua a entrada entre essas conexões pode separar o peer que respondeu ao proof do peer que recebe a chamada. O impacto sobre passphrase/respostas de aplicação não foi explorado nesta rodada para não inspecionar nem registrar credenciais. Esta consequência precisa ser considerada na decisão do threat model antes de distribuição; não é apresentada como exploit executado.

## P2 smoke Tauri/WebView

BLOCKED e continua aberto. O pré-cheque atual de `System Events` retornou `false`. A tentativa real anterior neste mesmo host produziu o erro literal `osascript é um acesso assistivo não permitido (-1728)`. Não alterei permissões nem tentei contornar a recusa; nesta rodada não iniciei uma janela que não poderia observar. Build, wrapper e a integração Rust acima não substituem evidência da WebView.

Roteiro manual curto para o proprietário, usando somente a credencial sintética pedida pelo launcher:

1. Execute `/tmp/mac00311-real-smoke-audit-4anh73_t/manual_smoke.py`; digite uma credencial inventada apenas no prompt oculto.
2. Na janela, aguarde runtime pronto, abra sessão e confira estado ativo.
3. Confirme explicitamente `mission:read` em `dom_synthetic_a` e leia a missão sintética.
4. Revogue e confira a confirmação da UI. Se a UI permitir nova tentativa real, faça-a e registre a negação. Se o botão sumir, registre essa limitação; isso não prova negação pelo servidor.
5. Feche e abra nova sessão; confirme grant inativo e encerre normalmente.

O resultado do proprietário deve ser identificado como relato manual, não observação do agente. Sem esse resultado, P2 aberto.

## P3 separados

| Achado | Evidência/impacto | Bloqueia marco local atual? | Gate de distribuição |
|---|---|---:|---:|
| Parse permissivo da expiração / divergência com ISO | Rust exige `expires_at_epoch_us` inteiro futuro para validade, mas aceita `expires_at` como qualquer texto não vazio de até 64 caracteres. A validade real usa microssegundos; a string ISO só alimenta a exibição e pode divergir. | Não para autorização com o FastAPI atual; o servidor continua autoritativo. | Corrigir consistência do DTO e rejeitar ISO divergente antes de ampliar consumidores. |
| Data sem fuso | A API atual gera datas aware UTC e a validação de grant rejeita datetime sem fuso. O parser Rust não valida o fuso da string ISO recebida; consumidores locais podem interpretá-la em timezone diferente. | Não com o servidor atual. | Exigir timezone e consistência em todo DTO distribuído. |
| UI mostra grant ativo brevemente além da sessão/grant | A UI atualiza status a cada 500 ms; até a próxima atualização pode exibir o estado anterior. Rust limpa no prazo exato e o servidor verifica cada leitura. | Não; é atraso visual limitado pelo polling, sem extensão de autorização. | Exigir estado temporal coerente antes de distribuição. |
| Resposta de criação do grant perdida | Se o servidor criou o grant e a resposta se perdeu, Rust não conhece o ID para revogar; repetição pode receber `grant_conflict`. Encerrar a sessão invalida o grant e permite novo consentimento. | Não bloqueia o marco local; há recuperação por fechamento da sessão, mas UX não é direta. | Definir recuperação idempotente com UX clara antes de uso mais amplo. |
| Caminho absoluto e passphrase por environment no launcher de release | `helper_command` deriva o script de `CARGO_MANIFEST_DIR` e copia `JARVIS_LOCAL_PASSPHRASE` do ambiente. Funciona no checkout de desenvolvimento usado aqui, mas não constitui empacotamento portátil nem armazenamento seguro de credencial. | Não para o teste local sintético. | **Bloqueia distribuição** até empacotar o runner e definir armazenamento/entrada segura da credencial. |

Nenhum desses P3 foi alterado nesta branch.

## Comandos, resultados e falhas preservadas

Comandos executados na worktree desta branch, salvo indicação:

| Comando/ação | Resultado |
|---|---|
| `git worktree add -b feat/jarvis-g6-mac-003-1-2-supervisor-auth ... 059871ff7e753bc4e785d77d5f209c6ebef33d71` | PASS; nova worktree/branch sem tocar candidata ou main. |
| `cargo test -v --locked --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --features mac003-production-supervisor-test --test mac003_production_supervisor --no-run` (compilação inicial do mesmo alvo com execução) | Evidência: `desktop_lib` foi compilado como rlib normal sem `--cfg test`; integração foi compilada com `--test` e importou esse rlib. Sem atualização de dependência/lockfile. |
| `cargo test --locked --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --features mac003-production-supervisor-test --test mac003_production_supervisor -- --test-threads=1 --nocapture` (final) | PASS: 1 teste, 4,38 s; FastAPI real, sessão/grant/leitura/revogação, STOP, EOF, crash/restart, reap e limpeza UDS. |
| `cargo test --locked --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --lib runtime_manager::tests::stopped_starting_ready_stopping_stopped -- --exact --test-threads=1` | PASS: 1 passed, 82 filtrados; código do harness unitário compilado. |
| `cargo check --locked --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --lib` sem feature de integração | PASS: 167 crates compiladas do cache local; caminho normal de produção compilou. |
| `cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml -- --check` | PASS final. |
| `git diff --check` | PASS final. |
| Pré-cheque `osascript ... get UI elements enabled` | `false`; smoke da janela não foi executado. Erro anterior de janela: `(-1728)`, acima. |

Falhas intermediárias mantidas no registro:

1. `cargo fmt --check` inicial falhou nos trechos novos; `cargo fmt` corrigiu e a verificação final passou.
2. Primeira integração falhou porque a comparação da sonda incluiu a quebra de linha final. A saída sanitizada mostrou os resultados esperados; `trim_end` corrigiu apenas o comparador.
3. Uma compilação seguinte falhou com dois `E0425`: a renomeação para `_instance_id` atingiu a listagem de produção em vez do probe de teste. A variável original foi restaurada e o underscore aplicado no local certo.
4. A execução seguinte avançou e falhou porque a asserção esperava `code=grant_required` no JSON do Rust; esse DTO retorna mensagem de UI. A verificação foi alinhada à mensagem “concessão de leitura está ausente”, enquanto o probe do servidor verificou a resposta de autorização correspondente.
5. A compilação unitária focada revelou 16 referências `start_test`/`restart_test` no módulo separado de testes de linearização. As chamadas foram renomeadas e o teste unitário focado passou.
6. Após os ajustes, o alvo completo final passou e registrou todos os estágios PASS; as falhas anteriores não foram apagadas nem contadas como passes.

Não foram instaladas dependências. O alvo de integração reutilizou, por symlink temporário em `apps/api/.venv`, o virtualenv existente da worktree candidata; o symlink foi removido após os testes. `Cargo.lock`, lockfiles JS/Python, API de produção, migrações, contrato SQLite e documentos canônicos MAC-002 permaneceram inalterados.

## Higiene, classificação e recomendação

Após a integração: zero processo do `serve.py`/alvo de teste, zero UDS correspondente, zero listener TCP do produto, zero diretório sintético temporário. Os processos auxiliares do seeder e da sonda foram aguardados pelo próprio teste. O checkout compartilhado preservou o branch e os arquivos preexistentes.

- **P0:** nenhum encontrado nesta revisão focada.
- **P1:** nenhum exploit de leitura sem credenciais foi reproduzido. O intervalo entre proof e a nova conexão de aplicação permanece risco de same-UID a decidir, descrito acima.
- **P2:** o caminho real do supervisor passa após nova cobertura; a janela Tauri/WebView continua aberta por `-1728`; a semântica de autenticação cliente/servidor precisa de decisão formal antes de chamar o transporte de mutuamente autenticado.
- **P3:** cinco itens listados acima; caminho/segredo do launcher bloqueia distribuição.

Recomendação: manter a candidata fora da `main`; fechar o P2 de supervisor somente na reauditoria do alvo de integração e fechar o P2 WebView apenas com execução manual observável. Registrar decisão explícita sobre o sentido da prova MAC-002 antes de documentação de segurança para distribuição. Não constitui aceite formal nem autorização para trabalho posterior.
