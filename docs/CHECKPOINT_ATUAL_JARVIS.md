# JARVIS — checkpoint técnico vivo

**Data da coleta:** 2026-11-07 (America/Sao_Paulo)
**Estado:** PARCIAL — leitura de repositório e contratos; não foram executados testes novos de produto.
**Escopo:** JARVIS Victor OS. **Não representa o estado da Friday**, que é um projeto independente.

## Baseline

- Repositório público: `victorpeborges-ADS/Jarvis-Victor-OS`.
- Branch consultada em GitHub e no Mac: `feat/gate2.0-e-integracao-web-api`.
- Commit da branch inspecionada: `495bc21c58936a934c3ff61e148f74431a0cb71a`.
- Fonte canônica de regras: `AGENTS.md` do commit acima.
- Foram observadas alterações locais **ainda não commitadas** no checkout principal do Mac. Este checkpoint não certifica esse conteúdo nem substitui inspeção da worktree. **Não executar reset/clean/stash nem sobrescrever esses arquivos por suposição.**

## Implementado/aceito conforme documentação versionada

- Gate 1: interface DEMO e jornadas sintéticas; aceitação técnica registrada.
- Gate 2.0-B e C.1: fundações, SQLite local separado de fixtures e concessões voláteis, conforme documentação.
- Gate 2.0-C.2: backup/restauração cifrados aceitos **somente para bases sintéticas descartáveis**.
- Gate 2.0-D: provider Calendar **simulado**, tecnicamente aceito em seu escopo.
- Gate 2.0-E: integração web/API **sintética** implementada na branch consultada, com relatório de testes versionado em `docs/GATE2_0E_INTEGRACAO_WEB_API.md`; **auditoria independente e consolidação ainda pendentes** de acordo com `AGENTS.md` e `README.md`.

**Evidência de testes histórica, não reexecutada aqui:** o relatório do Gate E registra 138 testes de API, 34 testes Vitest e 28/28 E2E, além de typecheck, lint e build. Esses números só comprovam o que o relatório afirmou na época; não garantem situação atual do Mac.

## Não verificado ou não autorizado

- Modificações não commitadas do roadmap e dos handoffs locais podem alterar o planejamento; **não constam necessariamente do GitHub público**. Comparar antes de propor próximas etapas.
- OAuth real, Google Calendar/Gmail/Drive reais, LLM, redes externas, dados pessoais/institucionais, deploy, acesso remoto e escrita externa **não são liberados por esta documentação**.
- Qualquer status de agente autônomo em VPS, Friday P30/P32, plugins locais ou execução em segundo plano **não foi auditado nesta coleta** e deve ser acompanhado por seus próprios registros privados e testes.

## Decisão do ciclo

Adotar `docs/PROTOCOLO_CONTINUIDADE_CONVERSAS.md` para reduzir o contexto das conversas, manter checkpoints rastreáveis e separar memória privada de documentação pública. Não fundir Friday ao JARVIS nem converter relatórios antigos em status atual.

## Primeira ação na retomada

1. Ler `AGENTS.md`, este checkpoint e `docs/ROADMAP_INTEGRADO_2026-10-17.md`.
2. No Mac, inspecionar `git status` e `docs/ROADMAP_INTEGRADO_2026-10-24.md` (se existir localmente), sem alterar o trabalho existente.
3. Conferir pendências/aceite do Gate E e eventuais worktrees candidatas; registrar divergência `LOCAL × GITHUB`.
4. Escolher **uma** frente com evidência e autorização, executar os testes relevantes e atualizar este registro ao encerrar.

## Handoff e links

- Contrato canônico: [AGENTS.md](../AGENTS.md)
- Gate E: [documentação e evidências](GATE2_0E_INTEGRACAO_WEB_API.md)
- Roadmap versionado: [roadmap de 17/10](ROADMAP_INTEGRADO_2026-10-17.md)
- Protocolo: [continuidade](PROTOCOLO_CONTINUIDADE_CONVERSAS.md)

**Nota de persistência:** este documento é versionado. Antes de reusar, verificar se a branch/commit e o estado do ambiente ainda correspondem a esta coleta.

## Adendo: capturador técnico de continuidade — 07/11/2026

- **IMPLEMENTADO NA BRANCH DOCUMENTAL DESTA PR:** `scripts/continuity_capture.py` registra metadados Git em `.git/continuity/checkpoint.json`, privadamente; fornece `capture`, `resume` e wrapper opt-in `run -- comando`.
- **TESTADO SINTETICAMENTE:** 5/5 casos de `scripts/test_continuity_capture.py`, incluindo privacidade e erro de execução.
- **EXERCITADO LOCALMENTE NO CHECKOUT PRINCIPAL:** captura do Git em `495bc21c5893`, com 3 arquivos rastreados modificados e 3 não rastreados naquele momento; nenhum arquivo do projeto principal foi limpo, alterado ou commitado por essa captura.
- **NÃO REALIZADO:** monitoramento automático do comprimento dos chats, interceptação automática de Codex Desktop/Friday/Cursor, atualização automática de decisões ou testes do JARVIS e merge deste PR.
