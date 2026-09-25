# ADR 005 — minimização no cliente, autorização no servidor e revogação

**Estado:** aceita para a implementação sintética local. Não autoriza conectores reais.

## Contexto

O builder de contexto executa no navegador e recebe identificadores/escopos fornecidos pelo chamador. Esses filtros reduzem o conteúdo enviado à etapa seguinte, mas podem ser adulterados pelo cliente. Não são credenciais nem uma fronteira de autorização.

## Decisão

- O cliente chama os conjuntos de filtro de `client_visible_source_ids` e `client_visible_domains`, rejeita timestamps inválidos/futuros e omite conteúdo vencido ou desatualizado.
- Cada rota do servidor continua validando sessão e concessão antes de consultar o SQLite. Filtros visuais ou no cliente nunca autorizam consultas.
- Leituras de eventos fazem validação de concessão e seleção SQLite sob o mesmo lock usado pela revogação. A operação é linearizada quando obtém o lock: se a leitura entrou primeiro, a revogação espera e a leitura pode ser entregue depois; se a revogação entrou primeiro, a consulta subsequente falha fechada. Nenhuma consulta de provider/rede ocorre dentro desse lock.
- O catálogo sintético requer ao menos uma concessão Calendar ativa. Calendários ainda sem classificação são metadados de escolha visíveis ao principal concedido; itens classificados só aparecem quando o domínio está coberto por concessão. A classificação e a sincronização também revalidam o domínio no servidor.

## Limites

Esta semântica serializa operações dentro de um único processo. Não coordena múltiplos workers/processos e não recolhe bytes de uma resposta já linearizada antes da revogação. Antes de conectar dados reais, a implantação deve manter uma única autoridade de grant ou substituir o lock por coordenação transacional compartilhada, além de revisar o escopo OAuth/provider e a exposição do catálogo.
