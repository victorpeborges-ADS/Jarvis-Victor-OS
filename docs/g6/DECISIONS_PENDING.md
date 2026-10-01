# Decisões pendentes e restrições

Este registro distingue restrições confirmadas pelo produto de opções técnicas ainda sem aprovação. G6.0 não cria ADR para item em aberto.

## Restrições já definidas

| ID | Restrição | Consequência |
|---|---|---|
| R-01 | Clientes não decidem autorização; backend Victor OS é a autoridade de produto. | Nenhum SDK/UI nativo pode substituir validações do servidor. |
| R-02 | G5 permanece aceito no escopo local, sintético, monoprocesso ADR-010. | Não afirmar account identity, multiworker, host-admin protection ou remote security. |
| R-03 | API fica loopback-only no próximo escopo local. | Android não acessa Mac por LAN ou túnel. |
| R-04 | Voz começa com PTT; não usa wake word nesta linha. | Microfone não é habilitado por G6.0. |
| R-05 | Áudio bruto não fica armazenado por padrão; voz não aprova ações sensíveis sozinha. | Aprovação visível e revalidação do servidor são mandatórias. |
| R-06 | Sem conta real, OAuth, API externa paga, cloud, sync, push, deployment ou dados pessoais nesta sprint. | Nenhuma dependência/credencial/provider novo. |

## Decisões técnicas pendentes

| ID | Pergunta que precisa de resposta | Opções/critério | Bloqueia |
|---|---|---|---|
| DEC-01 | Como empacotar Python API para sidecar macOS? | PyInstaller conforme referência Tauri; outra distribuição congelada; avaliar tamanho, compatibilidade arm64/x86_64, supply chain, notarização e debug. Nenhum método escolhido. | PR de sidecar distribuível G6.1 |
| DEC-02 | Qual canal do parent receberá porta e readiness do child? | stdout estruturado com challenge, pipe local ou socket IPC privado; exigir posse do child, nonce, parse restrito e ausência de segredo em log. | Runtime Manager G6.1 |
| DEC-03 | Porta dinâmica ou endpoint IPC intermediado? | Bind loopback efêmero mantido pelo child versus bridge Tauri estreita; avaliar origem/cookies, CSP, superfície de comandos e port collision. Nunca conectar em serviço existente. | Transporte autenticado G6.1 |
| DEC-04 | Qual é a origem efetiva do WebView Tauri em build distribuível? | Inspecionar URL/scheme do artefato; autorizar exatamente essa origem ou escolher IPC tipado; sem CORS wildcard, null ou reflection. | Primeiro request autenticado G6.1 |
| DEC-05 | Como sinalizar readiness real? | Health interno autenticado por challenge, report pelo pipe e validação de versão/DB; endpoint atual /health é DEMO mock e não é suficiente. | UI Ready G6.1 |
| DEC-06 | Como versionar API já existente sem prefixo? | Freeze OpenAPI e compatibilidade por schema; escolher path/header e política de deprecation antes de client release. | Geração de client G6.1 |
| DEC-07 | Tipos gerados ou SDK comum? | Começar com OpenAPI->TS reprodutível; SDK somente quando dois clientes API estiverem conectados e compartilharem transporte. | PR integração da Web e Mac |
| DEC-08 | Política de backup/migração do SQLite do .app? | Backup consistente, upgrade, falha, recuperação e downgrade; não assumir migration reversível. | Release atualizável G6.1 |
| DEC-09 | Quais providers de voz usar em cada plataforma/idioma? | API de sistema, provider externo, ou provider licenciado; medir disponibilidade offline, locale, qualidade, dados enviados, preço, licença e interrupções. Nenhum selecionado. | G6.2 real |
| DEC-10 | Aprovação por voz pode existir? | Contrato inicial exige aprovação visual explícita. Qualquer proposta de gesto vocal futuro demanda análise de assurance e aceite próprio; backend continua obrigatório. | Feature de voice approval |
| DEC-11 | Qual mecanismo Tauri protege single instance e saída/crash? | Runtime Manager próprio + plugin suportado; separar single-instance da gestão do child. Testar bundle macOS. | G6.1 |
| DEC-12 | Qual subgate escolhe modo de continuidade Android? | Comparar A–E em G6.4 com privacidade, segurança, custo, disponibilidade e recuperação. | Qualquer sync/remoto |
| DEC-13 | Qual política de identidade e recuperação? | Identidade produto vs usuário local, enrollment, sessão por device, chave, revoke offline, perdida/recuperada. | G6.4 |
| DEC-14 | Quais IDs e retenção para conversation? | Definir autor, persistência, domínio, exclusão, export e sync. Não há conversation_id atual canônico. | Continuidade e voice history |
| DEC-15 | Qual custo recorrente é aceitável após protótipo? | STT/TTS, hosting, storage, sync e push têm cenários de preço e consentimento separados. R$0 é objetivo do protótipo, não previsão de produção. | Provider pago/serviço remoto |

## Decisões que não devem ser confundidas

- Um port number aleatório não é autenticação; a posse do child, o handshake e a validação de origem também importam.
- Um Keychain/Keystore não cria identidade de usuário nem decide grants.
- Um transcript correto não é um ato de aprovação e um ID de missão não é prova de acesso.
- Um ícone Capacitor/permission INTERNET não torna API local alcançável pelo Mac.
- Uma resposta em cache não confirma que revisão continua atual; version e digest devem ser revalidados.
- Tauri segue como candidato atual porque já existe scaffold; trocar framework exige justificativa concreta num ADR, não uma preferência estética.

## ADRs

Nenhum ADR G6 é criado nesta entrega: as restrições acima já derivam do pedido e ADR-010, enquanto detalhes de port, origem, empacotamento, identity e provider continuam pendentes. Quando uma decisão de implementação for tomada num subgate, registrar contexto, alternativas, consequências, threat boundary, rollback e evidência no ADR correspondente.
