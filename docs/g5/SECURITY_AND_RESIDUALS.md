# Segurança e Residuais — G5

Análise de segurança, garantias e riscos residuais da sprint G5.

## Garantias de segurança e autorização

1. **Separação de privilégios**:
   - `mission:read`: autoriza leitura de missões e consulta da fila de revisão.
   - `mission:write`: autoriza criação e execução de etapas determinísticas. Não autoriza decidir ou aprovar artefatos.
   - `mission:review`: autoriza registrar decisões de revisão sobre artefatos no domínio correspondente.
   - Concessões de `calendar_sim` não concedem qualquer acesso a rotas de revisão.

2. **Hierarquia de locks e ausência de deadlocks**:
   - Ordem estrita: lock em memória de concessões (`_grant_lock`) é adquirido **antes** da transação SQLite (`BEGIN IMMEDIATE`).
   - Callers de transação SQLite nunca tentam adquirir o lock de concessão enquanto estiverem dentro de uma transação.
   - Revogação de concessão adquire `_grant_lock`. Se a revogação ocorre antes do commit da decisão, a decisão é bloqueada e falha fechada com 403 `MissionDenied`. Se o commit da decisão ocorreu primeiro, a decisão foi gravada de forma atômica e consistente antes da revogação.

3. **Imutabilidade e integridade criptográfica**:
   - A decisão de aprovação grava o hash SHA-256 exato do snapshot do artefato avaliado.
   - Se o rascunho sofrer alterações subsequentes, uma nova versão (`v2`) é criada em estado `pending`; a versão aprovada anterior permanece preservada e inalterada no histórico append-only.

4. **Tratamento de corrupção**:
   - Registros de revisão com integridade comprometida (ex: documento JSON malformado) respondem 409 `integridade do registro de revisão` em leitura unitária e são isolados na listagem sem ecoar conteúdo sensível e sem deletar linhas do SQLite.

## Riscos residuais e limites

- **Identidade de revisores**: o sistema opera localmente com o principal sintético da sessão (`owner`). Não há autenticação biométrica ou assinatura digital de identidade civil. A autoria registrada é o principal da sessão local.
- **Conhecimento staged**: o conhecimento derivado (`mission_knowledge`) é mantido em estado `staged` e não é promovido automaticamente pela aprovação do artefato, pois o contrato de governança de memória de longo prazo pertence a um gate futuro.
- **Garantias transacionais**: as garantias são atômicas locais (ACID no SQLite local). Não há garantia de exactly-once distribuído nem replicação multi-instância.
- **Grants voláteis**: concessões e sessões permanecem na memória do processo servidor. Um reinício do processo invalida as concessões existentes, exigindo nova emissão explícita.
