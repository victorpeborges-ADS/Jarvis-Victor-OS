# Nota — bloqueios do núcleo Mac na consolidação de 17/10/2026

Leitura da candidata `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`. Nenhum pytest, build, smoke ou abertura de app foi executado nesta leitura. Não havia processo de `serve.py` nem do app JARVIS; o build isolado mesmo assim não rodou, porque outros fluxos ainda gravavam a árvore. Smoke nativo continua BLOCKED.

## Empacotamento

- Dependência: decisão DEC-01 ainda aberta; `tauri.conf.json` marca `bundle.active` e `targets: all`, sem sidecar Python. O lançamento real continua na worktree, via `.venv` ou `python3.12`.
- Critério de aceite: instalação nova sem a árvore de código, sem `uv` global e sem o caminho desta worktree. Assinatura e notarização exigem certificado.
- Motivo do bloqueio: nenhum pacote foi produzido nesta verificação. Assinatura: BLOCKED. Build: NOT TESTED.

## Lançamento, encerramento e diretório de dados

O código de `apps/api/serve.py` e do supervisor foi lido nesta verificação. Sem argumentos, o bind usa `JARVIS_BIND_HOST` ou `127.0.0.1` e `JARVIS_BIND_PORT` ou `8000`, passa por `LocalServerConfig.validate()` e `assert_bind_host`, e sobe `create_app` com access log desligado e `proxy_headers` falso. No modo `--desktop-runtime`, o Uvicorn escuta o socket relativo `runtime.sock`, o cwd do filho é o diretório temporário `.jv-` com modo `0700`, e o banco vem de `JARVIS_DATABASE_PATH` ou, no Darwin, de `~/Library/Application Support/Jarvis/memory.sqlite3`. O parada manda `JARVIS_RUNTIME_STOP` e, após o timeout, mata o filho. O socket sai por `unlinkat` no descritor do diretório. A remoção desse diretório no `Drop` de `TransportSession` está sob `cfg(test)`. Execução desta verificação: NOT TESTED.

## Onboarding

- Dependência: D08, com modo offline visível, exportação, exclusão e desinstalação.
- Critério de aceite: primeiro uso explica o que fica neste Mac e não pede conta externa.
- Motivo do bloqueio: não há fluxo de primeiro uso no desktop da candidata. NOT TESTED.

## Backup, restore e exportação

`backup_cli.py` expõe `backup`, `restore` isolado e `activate` com confirmação. A exportação de dados do usuário não é um desses comandos; o contrato está no ADR-012. Tombstone e expiração de backup seguem sem decisão. Cifra do SQLite ativo: ADR-013, sem algoritmo escolhido. Execução desta verificação: NOT TESTED. Banco diário: BLOCKED.

## Observabilidade e recuperação

`GET /v1/health` do runtime nativo responde `ok`. O access log do Uvicorn fica desligado, o stderr do filho é descartado e o nível de log do modo desktop é `critical`. Há `recover_interrupted` para execução de missão aberta, `recover_activation` para ativação interrompida e handler 503 quando a memória local falha. Não há produto de métricas. Execução desta verificação: NOT TESTED.

## Voz, tela, acessibilidade

Voz: ADR-014. Observação de tela, ação nativa, câmera e gestos: sem código nesta candidata. Ação de tela: BLOCKED. Acessibilidade: o desktop tem `aria-*` e `prefers-reduced-motion`; auditoria WCAG desta verificação: NOT TESTED.

## Android, pareamento e sync

A prova offline lida está na worktree `/Users/vic/.codex/worktrees/jarvis-android-offline-proof-adr-20261012/Jarvis-Victor-OS`, branch `feat/jarvis-android-offline-proof-adr-012`, HEAD `06a9ba0`, ADR `docs/adr/012-android-continuidade-local.md`. Ela não foi copiada para cá. O `apps/mobile` da candidata continua scaffold; o README local diz que o APK não foi compilado. Pareamento e sync: BLOCKED. APK: NOT TESTED. Identificador de demonstração não é identidade.

## Conectores e provider real

Durante esta leitura apareceram, gravados por outro fluxo, `conversation_gateway.py`, `grounded_read.py` e `docs/g6/GROUNDED_READ_AND_REAL_PROVIDER_PROTOCOL_2026-10-17.md`. No fechamento também estava `apps/api/skill_registry.py`. Essas frentes ficam em andamento. O protocolo declara provider real BLOCKED até autorização de modelo, dados e custo. Esta consolidação não reexecutou o pytest citado nesse documento e não editou o registro de skills. OAuth, Gmail, Calendar, Drive e GitHub de conta real: BLOCKED. Módulo novo de conector falso não estava na lista final.

## Manifesto

`docs/g6/BUILD_MANIFEST_2026-10-17.md` está defasado. Dos 45 caminhos listados, 36 hashes ainda coincidem e 9 divergem: `local_captures.py`, `memory_store.py`, `native_app_api.py`, `test_daily_capture_gate.py`, `test_native_app_api.py`, `runtime_manager.rs`, `App.tsx`, `runtimeCommand.ts`, `runtimeCommand.test.mjs`. Nove caminhos locais não entram na lista, entre eles a conversa, a leitura lexical e os ADR-012 e ADR-013. O ADR-014 e esta nota foram escritos depois dessa comparação e também ficam de fora. O manifesto não foi regenerado: a árvore seguia em edição.

## Instruções

`docs/g6/PLANO_ATIVO.md` aponta para `/Users/vic/Freela/Jarvis-Victor-OS/docs/ROADMAP_INTEGRADO_2026-10-17.md`. O `AGENTS.md` da candidata não nomeia esta worktree e ainda diz que a `main` não foi avançada; essa frase não foi reescrita. O README do checkout do plano aponta o roadmap e não nomeia o caminho da candidata. Esse caminho continua na seção 10 do roadmap.
