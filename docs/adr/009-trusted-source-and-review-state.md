# ADR-009 — Estado confiável de fontes selecionadas e revisões

- **Status:** adotado para a candidata R5; não constitui aceite de gate.
- **Data:** 2026-09-29.
- **Contexto:** auditoria R4 identificou que classificações, estados e metadados persistidos podiam ser lidos como prova de origem ou decisão, embora fossem valores mutáveis no SQLite local.

## Decisão

Tratar campos persistidos como alegações. Cada leitura que exponha uma fonte selecionada ou uma decisão de revisão reconstrói a prova a partir do catálogo sintético no servidor, da missão e do domínio, do registro de conhecimento, do snapshot imutável da revisão e do ledger local. A autorização da requisição continua vindo da sessão/grant local volátil e dos filtros no servidor; a prova de uma fonte não cria nem amplia autorização.

Falha ou contradição resulta em quarentena fail-closed: omitir conteúdo, hash, proveniência e decisão; representar a fonte como `unverified/quarantined` e a revisão derivada como `pending`/rascunho. Registros inválidos não são apagados automaticamente.

Na migração, apenas linhas explicitamente marcadas como candidatas por `0015_selected_source_reconciliation` podem ser avaliadas para reconciliação única. A promoção exige igualdade de bytes com exatamente uma fixture versionada e coerência entre todos os vínculos. Registros desconhecidos ou ambíguos permanecem em quarentena. Reinícios revalidam as alegações atuais, mas não reabrem candidatos já recusados.

Importações não transportam autoridade. Estados importados que afirmem decisão (`approved`, `rejected`, `changes_requested`, `approved_locally`, `not_required`) são recusados e enviados à lista de quarentena da importação, sem escrita da missão ou ledger. Estados neutros de rascunho/pendência são normalizados para `draft`; apenas a decisão local registrada no ledger decide revisão.

## Consequências e limites

- A validação por leitura reduz a dependência de uma tarefa de reconciliação em background.
- A reconciliação transacional é serializada pelo writer SQLite; leituras e a revalidação seguem a mesma ordem de locks do repositório.
- O escopo continua sendo API local, processo único, grants de memória e fixtures sintéticas. Não há OAuth, autenticação remota, multiworker, API pública ou dados pessoais.
- Um usuário/processo com escrita irrestrita no banco local pode provocar negação de serviço ou adulterar dados; a aplicação tenta detectar inconsistências e ocultar dados, mas não protege SQLite contra o administrador do próprio dispositivo.
- Decisões sobre versões antigas continuam recusadas pelo contrato existente. Esta ADR não altera esse contrato.

## Alternativas consideradas

1. Confiar em `classification`, `state` e `review_state`: rejeitada, pois são valores persistidos editáveis.
2. Promover automaticamente por nome, hash declarado ou ID: rejeitada, pois não prova bytes nem vínculos.
3. Exigir autenticação remota ou grant durável para a R5: rejeitada, pois amplia o modelo além do gate local.

Veja também [invariantes](../r5/TRUSTED_STATE_INVARIANTS.md), [modelo de ameaças](../r5/THREAT_MODEL_LOCAL.md) e [compatibilidade de migração](../r5/MIGRATION_COMPATIBILITY.md).
