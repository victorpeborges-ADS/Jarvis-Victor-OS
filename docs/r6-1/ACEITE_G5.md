# JARVIS R6.1 / G5 — aceite formal

## Decisão

Em 2026-10-01, o proprietário aceitou formalmente o G5 da candidata JARVIS R6.1, SHA `ab7f856ee834b7f9923d914639e0e345dbf57322`, exclusivamente no escopo local, sintético e monoprocesso definido pelo ADR-010.

A auditoria independente final concluiu PASS técnico para esse SHA. O aceite formal registrado aqui é a decisão do proprietário; não altera o escopo técnico do parecer nem amplia a fronteira do ADR-010.

## Integração local

A branch `feat/jarvis-unified-r6-1-knowledge-provenance` foi integrada à branch local `main` por fast-forward a partir de `8e7c09bb303deb6fe444a3a455961519a5f414d2`, chegando ao SHA aceito acima. Este registro e a atualização do resumo de handoff foram feitos em commit documental separado na `main`. A branch candidata permanece preservada no SHA aceito.

Não houve push, tag ou deploy. O checkout compartilhado e seus quatro arquivos não rastreados foram preservados.

## Limites do aceite

Este aceite cobre somente dados sintéticos, execução local em loopback, um processo e sessões/grants voláteis. Não autoriza dados pessoais, OAuth, contas reais, rede remota, multiworker, deploy, G6 ou qualquer integração externa. Não há garantia criptográfica contra administrador capaz de controlar o host, o código e um estado SQLite integralmente coerente.

O G5 permanece dependente do catálogo sintético e da aplicação local como definidos no ADR-010. Este aceite não converte o banco SQLite em raiz criptográfica de confiança.
