# Arquitetura Android

## Estado real do scaffold

`apps/mobile` usa Capacitor 8, React e Vite, com `appId=app.jarvis.mobile` e `webDir=dist`. A UI atual é shell sintético. Outbox de capturas fica em localStorage; Missões é tela ilustrativa e Aprovações declara API desconectada. O README do app informa que o APK não foi compilado ou instalado e que Android Studio/SDK/adb não foram instalados. Não foi observada autenticação, conexão com endpoint, sync ou integração de plugin nativo de produto.

## G6.3 — Android Client Foundation

O primeiro escopo Android implementável mantém o dispositivo independente e honesto:

- Navegação e nomes seguem Agora, Conversa, Inbox, Domínios, Aprovações, Fontes, Missões e Integração. Em telas pequenas, destinos frequentes ficam na barra inferior e destinos secundários em Mais.
- Tipos vêm do OpenAPI/client gerado quando o contrato passar por G6.1, não de uma segunda política local.
- O estado local diferencia conteúdo DEMO, rascunho guardado no aparelho, API indisponível, sessão e concessão ausentes.
- Capturas locais informam “Neste aparelho” e não são apresentadas como Inbox sincronizada.
- Missões e aprovações conectadas mostram “Indisponível sem continuidade aprovada” até G6.4 decidir transporte e identidade.
- Sem worker, tarefa de background, push, retry de side effect, OAuth, conta real, dados pessoais ou backend remoto.
- Permissões nativas são mínimas; microfone só pode aparecer após G6.2, com solicitação no momento do uso e indicador de gravação ativo.

Capacitor disponibiliza uma ponte para plugins nativos, mas essa ponte não concede conectividade ou autoridade ao app. Recursos e limites de build Android devem ser confirmados quando houver autorização para preparar SDK; este pacote não instala toolchain. [Capacitor Android](https://capacitorjs.com/docs/android) · [ambiente oficial](https://capacitorjs.com/docs/getting-started/environment-setup)

### Loops locais não atravessam dispositivos

Em Android, localhost é o Android. O servidor G5 ou sidecar do Mac escuta apenas loopback do Mac. A API atual aceita bind apenas em loopback e não é endpoint LAN. A permissão INTERNET que aparece no manifesto do WebView não torna o servidor visível pela rede. Não substituir bind por "0.0.0.0", usar IP do Wi-Fi, túnel ou porta pública para “fazer funcionar”.

## Gate posterior: opções de continuidade

Nenhuma opção abaixo é selecionada por G6.0. G6.4 precisa escolher uma arquitetura e um threat model antes de qualquer endpoint remoto.

| Opção | Segurança | Complexidade | Custo potencial | Disponibilidade/offline | Push | Multi-device e conflitos | Privacidade |
|---|---|---|---|---|---|---|---|
| A. Backend central remoto | Superfície de servidor, identidade, sessão, TLS, abuso e operação passam a ser críticas; pode centralizar autorização. | Alta: hosting, backup, observabilidade, incidentes, identidade e migrações. | Recorrente provável em hosting, storage e tráfego; STT/TTS separado. | Disponível de qualquer rede; operação essencial depende da internet. Offline exige cache limitado. | Natural via provider, com vazamento em metadados se mal desenhado. | Um estado canônico central simplifica conflitos; exige regras de concorrência e exclusão. | Dados ficam no servidor conforme retenção aprovada; maior concentração. |
| B. Servidor de sincronização | A API atual permanece local, mas novo serviço recebe dados e precisa autenticar, proteger e reconciliar. | Alta: protocolo de delta, tombstones, versionamento, retry e migrações duplas. | Hosting e tráfego prováveis. | Uso local segue funcionando; convergência depende de rede. | Possível por broker. | Conflitos explícitos entre estados e revisões; sincronização de approvals é especialmente sensível. | Pode transmitir cópias amplas se seleção não for mínima. |
| C. Relay criptografado | Relay não precisa interpretar payload se criptografia ponta a ponta for correta; metadados/roteamento continuam expostos. | Muito alta: chaves, pareamento, recuperação, rotação, revogação e protocolo resiliente. | Serviço relay e tráfego podem ter custo. | Mensagens podem aguardar relay; offline prolongado atrasa continuidade. | Notificação pode revelar metadados; conteúdo deveria ser mínimo. | Criptografia não resolve conflito ou proveniência; exige sequência/versões. | Menor visibilidade de conteúdo para relay, maior complexidade de recuperação. |
| D. Dispositivo a dispositivo | Superfície de descoberta, NAT, confiança mútua, replay e exposição direta entre peers. | Muito alta: conectividade, pareamento, troca e revogação de chaves. | Pode reduzir backend contínuo, ainda há esforço de operação e relay de fallback. | Pode funcionar na mesma rede ou com canal direto; offline sem pareamento não. | Fraco sem serviço auxiliar. | Sincronização peer-to-peer e conflitos são difíceis de reproduzir/depurar. | Menos armazenamento central, mas disponibilidade e dados no peer. |
| E. Híbrida | Combina riscos de contas remotas, estados locais e rotas de sincronização; fronteiras precisam ser explícitas. | Muito alta: mais modos, decisões e matrizes de compatibilidade. | Variável; custo de cada caminho continua. | Melhor flexibilidade, com UX e semântica de cache mais complexas. | Possível; regras de privacidade devem variar por estado. | Pode priorizar servidor e manter offline local, mas precisa reconciliar com revisão e approvals. | Escolha granular possível; superfície de dados e políticas crescem. |

### Critérios de seleção do G6.4

1. O ator é uma identidade de produto ou somente dono local de um dispositivo?
2. Qual dado pode sair do aparelho e sob qual domínio, proveniência, consentimento e retenção?
3. O que significa revogar aparelho perdido quando está offline?
4. Onde a decisão autoritativa da missão/revisão acontece?
5. Como IDs, revisões, idempotência e exclusões sobrevivem a retry e conflito?
6. Qual modo funciona sem rede e como impedir que uma cópia stale seja confundida com aprovação atual?
7. Como recuperar chave e identidade sem transformar backup do SQLite em trust root?
8. Quais custos recorrentes e operadores passam a ser necessários?

## Contratos UX para Android

| Cenário | Texto/estado requerido |
|---|---|
| App aberto sem sync | “Somente neste aparelho. Ainda não sincroniza com o Mac.” |
| API indisponível | “Victor OS indisponível neste aparelho”; erro e tentar novamente. Não mostrar lista DEMO. |
| Login/grant inexistente | Explicar que sessão/grant local do Mac não se aplica aqui. Não sugerir que domain_id concede acesso. |
| Abrir missão compartilhada | Desabilitada com explicação até G6.4; nunca inventar o mesmo mission_id em outro banco. |
| Captura local | Rótulo local persistente, opção de apagar e sem enviar em background. |
| Permissão negada | Preservar recursos não relacionados; oferecer explicação e abrir configurações só por ação do usuário. |

## Fora do escopo desta arquitetura

OAuth, conta real, sync, remote backend, API LAN, Firebase/APNs, push, background sync, provisioning de dispositivos, APK release, armazenamento de chaves de identidade, importação automática de contatos/calendário/arquivos e dados pessoais.
