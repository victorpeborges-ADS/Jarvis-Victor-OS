# ADR 001 — contratos versionados para Missões

- Estado: aceito para protótipos locais sintéticos.
- Data: 2026-09-25.

## Decisão

`contracts/jarvis.missions.v1.schema.json` é o contrato serializado canônico para Missão, tarefa, checkpoint, artefato, contexto, conhecimento, manifesto de skill, capacidades de provider, concessão de dispositivo, envelope de sincronização e política de notificação. O cliente web declara tipos TypeScript alinhados. A API valida as definições pela mesma JSON Schema e usa Pydantic v2 para o objeto Missão que será manipulado pelo core.

Os exemplos em `contracts/jarvis.missions.v1.examples.json` são sintéticos e consumidos pelos testes TypeScript e Python. Alterações incompatíveis exigem nova versão de schema. Timestamps precisam carregar fuso. O orçamento da primeira versão é fixado em zero e os campos de contrato rejeitam propriedades desconhecidas.

## Limites

O contrato não persiste dados, não concede autorização e não representa execução real. A aplicação continua responsável por validar grants no servidor antes de entregar contexto. Campos de payload do `SyncEnvelope` permanecem envelopes opacos e versionados; consumidores devem validar cada item antes de usá-lo.

## Consequências

- O UI/Core pode evoluir com fixtures sem alterar SQLite ou dados de memória.
- A suíte compartilhada detecta divergências entre o validador Python e Ajv.
- A aceitação deste ADR não aprova Gate E nem qualquer integração com dados reais.
