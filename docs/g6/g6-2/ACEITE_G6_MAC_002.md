# Aceite formal e integração local — G6-MAC-002

## Decisão

A candidata funcional `c64ee0ae02274bc8ba6041edae043450b9313b6d` foi formalmente aceita no escopo deste registro e integrada localmente à `main` por fast-forward. A `main` antes da integração era `00753c58b97c3103d428bc6a0a9351f97b6c050d`; a candidata MAC-002.1 foi desenvolvida sobre a baseline intermediária `20626ebad5d01c6a8eee1a0366859e0be88764fd` e preserva a ancestralidade da `main` aceita.

A auditoria independente final reportou **PASS**, sem achados P0, P1 ou P2 na candidata. O aceite não representa aceite integral de G6.1 nem autoriza o próximo subgate.

## Escopo aceito

- Cliente desktop macOS local com runtime filho sintético supervisionado.
- WebView chama somente comandos Tauri tipados; Rust controla lifecycle, endpoint UDS e capability.
- Transporte HTTP/1.1 mínimo sobre UDS autenticado por prova HMAC com nonce novo, sem listener TCP.
- Isolamento por geração, readiness, stop e revogação em perda definitiva do canal do supervisor.
- Cleanup do socket ancorado ao descritor do diretório da geração, com comportamento fail-closed sob incerteza.

## Limites e riscos conhecidos P3

- O runtime continua sintético. FastAPI real, G5/SQLite, migrations e dados pessoais não foram conectados nem fazem parte deste aceite.
- O escopo é local e monoprocesso. Não inclui rede remota, API pública, multiworker, OAuth, contas reais, Android, Voice, assinatura/notarização ou distribuição de `.app`.
- Processo host com o mesmo UID pode causar negação de serviço e observar ou substituir paths. Administrador/root, processo host comprometido, SIGKILL e falhas do sistema operacional permanecem fora do modelo de proteção criptográfica.
- Diretórios de sessão `.jv-*` vazios podem permanecer no temp após o uso normal. Essa retenção é deliberada para evitar remover um diretório por pathname mutável.

## Advisory de dependência — dívida separada

`source-map-js@1.2.1`, transitiva de `vite → postcss`, tem advisory npm HIGH identificado como **GHSA-68fv-2mgg-jv7q / CVE-2026-93749**. É classificado como P3 de manutenção de segurança de build/dev e deve ser resolvido antes de distribuição/produção. Não houve atualização de dependências nem de lockfiles nesta integração.

## Integração e verificação

- Integração: `git merge --ff-only c64ee0ae02274bc8ba6041edae043450b9313b6d`, com fast-forward de `00753c58…` diretamente ao SHA funcional aceito.
- A árvore funcional final coincide com a candidata auditada. Não houve conflito nem alteração de runtime durante a integração; por isso a matriz de testes da auditoria não foi repetida.
- O registro deste aceite é um commit documental separado e não altera o runtime.
- Não foi feito push, tag ou deploy. MAC-003 não foi iniciado.

## Contrato canônico

O contrato canônico do desktop permanece **WebView → Tauri IPC tipado → Rust → HTTP/1.1 sobre UDS autenticado**. FastAPI G5 ainda não foi conectado.
