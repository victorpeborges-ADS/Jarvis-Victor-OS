# JARVIS G6.0 — Native Clients & Voice Foundation

**Status:** arquitetura preparada; implementação não iniciada
**Baseline:** main local em `82b3c244c796b68b181dbf127509caababd2258e`
**G5 funcional aceito:** `ab7f856ee834b7f9923d914639e0e345dbf57322`
**Branch de trabalho:** `feat/jarvis-g6-0-native-architecture-2026-10-01`

## Mandato e limites

O produto futuro é um JARVIS e um Victor OS com clientes web, macOS e Android e uma interface de voz. O servidor Victor OS permanece a autoridade para sessão, grants, domínio, autorização, missões, aprovações, proveniência, conhecimento confiável, contexto, skills e artefatos. Um cliente pode apresentar estado e coletar intenção; não pode emitir sua própria decisão de autorização.

G6.0 registra a arquitetura e prepara subgates. Este pacote não altera código funcional, configuração de clientes, API, banco ou permissões. Não habilita API remota, cloud, sync, OAuth, conta real, dados pessoais, voz real, microfone, serviço persistente, push, tag ou deploy.

G5 foi formalmente aceito no escopo local, sintético e monoprocesso do ADR-010. A aceitação não cria garantias contra administrador do host, não converte sessões ou grants voláteis em identidade remota e não amplia o trust root para fora do SQLite.

## Baseline conferido

- A main local estava no SHA indicado e é a origem exata da branch desta sprint.
- O SHA funcional G5 é ancestral da main local.
- A branch G6 começa no mesmo commit documental que registra o aceite.
- O checkout compartilhado anterior foi mantido sem mudanças; seus quatro arquivos não rastreados não foram levados à nova worktree.

## Auditoria do produto atual

| Área | Estado verificado no código | Consequência para G6 |
|---|---|---|
| Web — `apps/web` | Next.js 15.5 e React 19.1. Superfícies DEMO consomem fixtures separadas. A rota Integrado chama a API local por `apps/web/lib/local-api.ts`, usa cookies, CSRF, `credentials: include` e recusa endereço fora de loopback. Conversa web não é uma sessão conversacional persistente compartilhada entre dispositivos. | É a única jornada conectada à API sintética atual. Preservar separação DEMO/API e tornar contratos verificáveis para novos clientes. |
| API/Victor OS — `apps/api` | FastAPI, Python 3.12 e SQLite local. `serve.py` valida bind em loopback, desativa access log e inicia a aplicação explicitamente. Sessões e grants vivem em memória; grants usam lock; a inicialização migra o banco e recupera execuções de missão interrompidas. A rota `/real` chama dados sintéticos; o campo legado `dataset="real"` não significa conta/fonte externa. | É a autoridade de produto e segurança. Integrar o macOS por processo pertencente ao app, mantendo servidor e cliente em loopback. |
| Missões, revisões e conhecimento | Rotas locais versionam transições e revisões; artefatos/revisões têm IDs, revisão e snapshots. Autorização é revalidada em caminhos sensíveis e a decisão ocorre no backend. | Voice e clientes nativos encaminham intenção ao mesmo fluxo de missão e aprovação. Nunca validar decisão só em estado de UI. |
| macOS — `apps/desktop` | Shell Tauri 2 + React/Vite. Tauri apenas abre a janela; não há comando, sidecar, API, sessão, grant ou IPC funcional. Capturas fictícias usam localStorage. Missões e Aprovações informam que a API não está conectada. | G6.1 precisa criar o runtime local e substituir estados demonstrativos com estados reais explícitos, sem fingir integração nesta sprint. |
| Android — `apps/mobile` | Scaffold Capacitor 8 + React/Vite. A fila de capturas fictícias usa localStorage. Telas de missões são ilustrativas; Aprovações informa API desconectada. O projeto Android foi gerado, mas não há APK validado, SDK ou integração com API. | G6.3 pode construir cliente nativo e estados locais. O loopback do Android é o próprio aparelho, não o Mac; acesso compartilhado exige G6.4. |
| Contratos compartilhados | Não existe pacote `packages/jarvis-client`, `packages/contracts` ou `packages/ui-contracts`. A Web mantém tipos TypeScript manuais para chamadas locais; os shells têm seus próprios tipos de apresentação. | Manter OpenAPI/Pydantic no servidor como fonte de contrato. Avaliar client gerado durante G6.1; criar SDK compartilhado somente após consumidores reais justificarem manutenção. |
| DEMO e dados | As fixtures em `fixtures/demo.json` são sinalizadas. O caminho local sintético usa o SQLite isolado e não importa fixtures DEMO. | Falha de rede, sessão ou banco nunca troca dataset para DEMO sem escolha explícita. |

## Arquitetura alvo

Clientes mostram estados e enviam comandos tipados. O backend autentica a sessão, valida grants e domínio, aplica as transições e devolve estado com proveniência. Voice é uma entrada e saída do mesmo produto, não um agente paralelo.

O macOS inicia e acompanha uma API local pertencente ao próprio aplicativo. Android permanece cliente local até que o Gate de Identidade e Continuidade aprove um desenho de comunicação. A arquitetura detalhada está em [ARCHITECTURE.md](ARCHITECTURE.md); contratos em [CLIENT_CONTRACT.md](CLIENT_CONTRACT.md).

## Plano por subgate

| Subgate | Resultado | Bloqueio de segurança principal |
|---|---|---|
| G6.0 | Este pacote: arquitetura, contratos, ameaças, backlog e critérios. | Somente documentação; nenhuma fronteira nova habilitada. |
| G6.1 | macOS conecta ao Victor OS local por runtime sidecar gerenciado pelo app. | API presa a loopback; somente processo filho próprio; origem/CSP estreitos; pronto distinto de DEMO. |
| G6.2 | Fundação de voz local, push-to-talk em primeiro plano e mesma conversa/missão. | Sem wake word; nenhuma ação sensível aprovada por áudio; sessão e grants do backend permanecem exigidos. |
| G6.3 | Fundação de cliente Android, contratos e estados. | Sem sync, API remota, falsa continuidade ou acesso ao loopback do Mac. |
| G6.4 | Decisão formal sobre identidade de produto, identidade de dispositivo, sessões e continuidade. | Nenhum transporte multi-dispositivo até ameaça, provisioning, revogação e recuperação serem aceitos. |
| G6.5 | QA integrado dos clientes e dos estados de produto. | Aprovação de release independente; nenhuma expansão implícita de escopo. |

Critérios binários e fora de escopo: [SUBGATES.md](SUBGATES.md). Backlog com objetivo, arquivos, dependências, risco, testes e DoD: [BACKLOG.md](BACKLOG.md). Sequência e o primeiro PR executável: [IMPLEMENTATION_SEQUENCE.md](IMPLEMENTATION_SEQUENCE.md).

## Decisões de arquitetura nesta sprint

1. Backend/Victor OS é autoridade única para identidade autenticada local, sessão, grants e todas as decisões de produto protegidas.
2. G6.1 deve iniciar uma instância da API cujo processo seja possuído e supervisionado pelo .app; não deve anexar a um servidor encontrado por varredura de porta/processo.
3. O servidor continua em loopback. Portas e origens precisam ser negociadas de modo estreito e testadas no app empacotado.
4. Android não acessa o loopback do Mac. Até decisão do G6.4, a experiência móvel conectada fica indisponível e visível como tal.
5. Voz começa por ação explícita em primeiro plano; saída de áudio pode ser interrompida. Áudio bruto não é persistido por padrão.
6. Um “sim” reconhecido não aprova ação sensível. A interface mostra a aprovação; o servidor revalida a operação.
7. Os termos DEMO, local sintético, conectado e offline sempre identificam a origem real do estado.
8. Custo recorrente zero é uma meta do protótipo, sem promessa de preço zero para STT/TTS, sync, push ou backend remoto futuro.

Essas decisões são restrições de produto e direção para subgates; não constituem ADR para escolhas de implementação ainda abertas. As escolhas pendentes estão em [DECISIONS_PENDING.md](DECISIONS_PENDING.md).

## Próximos três itens concretos do G6.1

1. **G6-MAC-001 — Spike do Runtime Manager:** processo filho de teste controlado pelo Tauri, estado de inicialização/pronto/falha/encerramento, sem chamar a API de produto nem abrir dados. Validar empacotamento em macOS.
2. **G6-MAC-002 — Descoberta segura do endpoint:** definir porta efêmera, handshake de prontidão e origem real do WebView; documentar testes de colisão, processo falso e CORS/CSP antes de conectar rotas autenticadas.
3. **G6-MAC-003 — Integração API local:** habilitar endpoint estrito no runner/CORS, manter bind loopback e ligar a jornada de sessão, grants, missões e revisões com o client derivado do OpenAPI.

## Validação G6.0

Alterações limitadas a documentação. A validação desta entrega confere links, referências de código, presença/fences estruturais de Mermaid, whitespace Git, ancestralidade e integridade do repositório. Não havia validador Mermaid instalado; não foi instalado tooling. Suítes de API, Vitest, typecheck, lint, build e E2E não são executados porque nenhum código foi alterado.

> G5 permanece congelado e aceito no escopo ADR-010.
>
> G6.0 não altera o runtime funcional nem amplia a fronteira de confiança.
>
> Nenhuma integração externa, conta real, API pública, sync remoto ou voice real foi habilitada.
