# R5 — Compatibilidade de migrações

## Estratégia

O upgrade adiciona `0015_selected_source_reconciliation.sql` após `0014_curated_source_admission.sql`. A 0014 já reduz fontes legadas a `unverified/quarantined`, sem apagar linhas. A 0015 grava candidatos apenas quando os novos campos do catálogo estão nulos. A reconciliação R5 testa os candidatos contra fixtures e ligações que já estavam presentes; ela não usa classificação antiga como prova.

Falhas mantêm registros e metadados em quarentena. Hash/bytes desconhecidos, snapshot incompleto, referência cruzada, owner/domínio divergente ou conteúdo alterado não são “corrigidos” por inferência. A tabela guarda o resultado terminal `reconciled` ou `quarantined`, com motivo genérico, sem copiar conteúdo.

## Fixtures sintéticas

Os JSON em `apps/api/fixtures/migration_states/` fixam o último schema de cada estado e os registros que o teste planta:

| Estado | Última migração anterior | Perfil principal | Resultado de R5 |
|---|---|---|---|
| pre-G4 | 0007 | missão e evento | upgrade preserva ambos |
| G4 | 0008 | execução de missão | upgrade preserva execução |
| G5 | 0011 | revisão e ledger local | estado aprovado continua validável pelo ledger |
| R2-0013 | 0013 | fonte desconhecida | fonte preservada em quarentena |
| R3 pré-0014 | 0013 | bytes conhecidos com referência adulterada | fonte preservada em quarentena |

Além disso, `test_migration_preserves_unknown_sources_and_reconciles_only_byte_exact_fixture` cobre duas linhas antigas lado a lado: uma fonte com fixture e vínculos byte-exatos pode ser reconstruída; a fonte desconhecida permanece em quarentena. Os testes verificam `foreign_key_check`, `integrity_check`, repetição do initialize/reconcile e ausência de decisões de conhecimento fabricadas.

## Compatibilidade e backup

As fixtures são descartáveis, sintéticas e vivem nos testes. Não são uma cópia do banco padrão do usuário. Backup/restauração é exercitado com SQLite temporário, seguido por initialize e reconstrução da prova. Nenhum banco com dados pessoais é carregado ou atualizado.
