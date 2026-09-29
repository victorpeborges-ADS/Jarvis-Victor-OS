# R5 — Invariantes de estado confiável

## Vocabulário

- **Alegação armazenada:** campo mutável do SQLite ou de um documento importado, por exemplo `classification`, `state`, `review_state` ou `decision`.
- **Estado canônico:** resultado rederivado no servidor por comparação dos registros e do ledger.
- **Autorização:** decisão por requisição baseada em sessão local, grant ativo, domínio, recurso e owner; não é inferida de uma fonte ou de uma aprovação.
- **Classificação:** rótulo de uma fonte (`synthetic_verified` ou `unverified`); não dá permissão para lê-la.
- **Proveniência:** catálogo/fixture, identificadores e vínculos que demonstram de onde vêm os bytes; não prova aprovação humana.

## Prova de fonte selecionada

`prove_source` exige, em conjunto:

1. fixture ID, catálogo, versão, hash, bytes, nome e proveniência correspondentes à fixture permitida no servidor;
2. owner, missão e domínio iguais em fonte, missão, conhecimento e revisão;
3. conteúdo do conhecimento igual, byte a byte, à fixture e hash esperado;
4. revisão de artefato versão 1, snapshot com hash íntegro, referência à fonte selecionada e domínio correto;
5. payload do artefato atual igual ao snapshot, ignorando apenas os campos derivados de estado de revisão.

Qualquer divergência torna a prova falsa. As projeções de fonte, missão, revisões, conhecimento e contexto então omitem conteúdo e metadados confiáveis. Owner incompatível continua invisível por escopo, em vez de ser enumerado a outro principal.

## Prova de decisão

- `mission_artifact_reviews.state` isolado não é prova de decisão.
- Uma revisão pendente é válida se não houver decisão nem metadados residuais de decisão.
- Uma revisão decidida exige uma única linha do ledger imutável, com igualdade de owner, missão, artefato, versão, hash, decisão, ator, justificativa, instante e snapshot.
- A versão mais recente também precisa corresponder ao artefato atual da missão. Divergência retorna a projeção `pending`/`draft` e não entra em filas de aprovados nem em contexto de conhecimento.
- Uma decisão de conhecimento depende da decisão canônica da revisão de origem e da igualdade do conteúdo/hash. Somente decisões aprovadas e atuais podem entrar no contexto.

## Migração e importação

- `0014` rebaixa registros legados para quarentena. `0015` registra os únicos candidatos elegíveis para tentativa de prova byte a byte.
- Reconciliação só lê candidatos `pending`; candidato reconciliado ou recusado não é reavaliado como oportunidade de promoção.
- Inicialização/reconciliação é idempotente. Backup/restauração e reinício reconstroem provas a partir do banco restaurado; persistência não converte uma alegação em verdade.
- Importar estados de decisão não cria ledger, missão aprovada nem contexto. Estados neutros tornam-se rascunho local.

## Ordem de concorrência

As escritas e reconciliações usam transações `BEGIN IMMEDIATE` do store. Provas são lidas dentro da transação de leitura/escrita que forma a resposta. A revalidação não chama uma API externa, não espera outro lock sob o lock de missão e não introduz inversão de ordem. Os probes concorrentes cobrem leitura→reconciliação e reconciliação→leitura, além de importações simultâneas com a mesma chave.

Esta coordenação é por processo e SQLite local; não reivindica suporte multiworker. A sessão e os grants continuam em memória, expiram/revogam conforme o mecanismo existente e não são transferidos para outro processo.
