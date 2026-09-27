# Auditoria de entrada de fontes e documentos — R4

## Resultado por caminho

1. **Fonte selecionada.** O achado P1 estava em `apps/api/selected_source_api.py`: `confirm_synthetic=true`, nome e hash declarados pelo cliente permitiam armazenar texto arbitrário como `selected_original`. A reprodução prévia respondeu HTTP 201. R4 removeu o contrato de envio de texto e passou a aceitar somente `fixture_id` do catálogo do servidor.
2. **Importação de missão.** `POST /real/missions/import` recebe um lote versionado de documentos `Mission` e exige `confirm=true`. `MissionRepository.import_valid` valida contrato e identidade, persiste os artefatos e cria revisões pendentes. Não grava linhas em `selected_synthetic_sources` ou `mission_knowledge`. O montador de contexto lê somente `mission_knowledge` aprovada; as skills determinísticas recebem esse contexto, não o conteúdo bruto dos artefatos importados. A importação permanece um recurso de documento local, não uma rota de admissão de fonte.
3. **Revisão de artefato.** `/real/reviews/{id}/revise` pode receber texto para artefatos comuns depois de `changes_requested`. Para artefato vinculado a uma fixture selecionada, R4 recusa a revisão: o conteúdo é canônico e não deve mudar. Uma versão de revisão antiga continua ligada ao seu próprio ID/hash e o backend não aceita decisões para versões anteriores.
4. **Inbox e captura rápida.** As áreas do Gate 1 gravam em `localStorage` e usam fixtures DEMO. Elas não chamam a API de fontes. A transferência de Missões é o caminho distinto descrito no item 2.
5. **Calendar e eventos.** O provider Calendar é um simulador de servidor; os endpoints aceitam IDs de recurso permitidos e alterações de evento tipadas. Não há upload de documento nesse caminho.
6. **Backup/restauração.** O arquivo preserva o banco local. Restaurar não cria decisões nem muda classificação; os estados `unverified` e `quarantined` são persistidos.

## Comportamentos verificados

- Campos extras com conteúdo, nome, hash, confirmação ou classificação são rejeitados com HTTP 422 genérico; o texto não é devolvido no erro.
- ID desconhecido, conteúdo conhecido adulterado, hash/nome/classificação falsos e bytes extras não geram gravação parcial.
- Replays idênticos retornam a mesma fonte; reutilização de chave com outra fixture conflita; duas submissões concorrentes idênticas criam uma única linha.
- Falha SQLite antes da inserção da fonte reverte missão, artefato, snapshot e conhecimento.
- Migração preserva uma fixture byte a byte apenas após prova do snapshot. Texto desconhecido continua retido, sem decisão aprovada.
- Quarentena oculta conteúdo em missão, fila/detalhe de revisão e lista de conhecimento, recusa decisões e omite contexto.
- Backup/restauração preserva `classification`, `state`, ID da fixture, versão de catálogo e chaves estrangeiras.

## Limites

A verificação é uma comparação exata com um conjunto pequeno de fixtures versionadas. Não é classificador de PII e não consegue avaliar perfeitamente textos arbitrários. Documentos `Mission` importados continuam locais e visíveis no escopo da missão que os importou, mas não ganham status de fonte nem entram automaticamente em conhecimento/contexto. As provas usam exclusivamente conteúdo sintético.
