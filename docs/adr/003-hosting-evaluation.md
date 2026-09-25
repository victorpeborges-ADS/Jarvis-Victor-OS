# ADR 003 — avaliação preliminar de hospedagem

- Estado: decisão adiada; nenhuma plataforma escolhida.
- Revisado em: 2026-09-25, documentação oficial consultada nesta data.
- Escopo: análise documental; nenhum recurso cloud, conta, billing ou deployment criado.

## Matriz preliminar

| Critério | Workers + D1 | Cloud Run container |
|---|---|---|
| FastAPI/Python | FastAPI aparece na documentação oficial de Python Workers. O runtime usa Pyodide/WebAssembly e o ecossistema de wheels PyEmscripten ainda tem lacunas; a API atual com Uvicorn, `sqlite3`, dependências bloqueadas e fluxo de backup não foi portada nem compilada. **Compatibilidade direta não provada.** | Cloud Run suporta aplicações Python em container; empacotar o runner atual parece possível, mas imagem e comportamento ainda não foram construídos/testados. **Compatibilidade direta não provada.** |
| Banco | D1 expõe SQL com semântica compatível com a maior parte das convenções SQLite, mas exige API/bindings D1; não é o `sqlite3.Connection` local. Há SQL e PRAGMAs limitados. O adapter e as migrações deste repo não foram portados. | O filesystem gravável do container é efêmero; SQLite local não pode ser tratado como banco durável compartilhado numa frota que escala. Persistência exige avaliação de Cloud SQL ou montagem de rede. Nenhuma foi configurada. |
| Migrações | Wrangler mantém registro de migrações e aplica arquivos sequenciais. Equivalência transacional/semântica com as migrações e o runner Python deste repo não foi verificada. | O runner do repositório poderia continuar dentro do container apenas depois de resolver armazenamento compartilhado, startup concorrente e migrações entre instâncias. Não testado. |
| Concorrência | Cada D1 database é single-threaded e processa consultas uma a uma; volume e contenção por usuário não foram medidos. | Escala horizontal permite múltiplas instâncias; SQLite em disco local não coordena transações entre elas. O desenho de banco externo e limites de conexão não foi feito. |
| Cold start e runtime | Python Workers são descritos como fast-booting, mas nenhum benchmark do código JARVIS foi executado. Worker possui CPU/memória e limites de startup dependentes do plano. | Scale-to-zero cria instância para uma nova solicitação e pode aumentar latência. Nenhum container foi construído e nenhum tempo foi medido. |
| Scheduler/filas | Workers oferece Cron/Queues/Workflows como produtos, mas contratos, limites operacionais, custo e semântica de repetição ainda não foram verificados para o JARVIS. | Eventos/filas podem ser adicionados a serviços Cloud Run; scheduler externo, autorização e custos não foram modelados. Sem job sempre ligado nesta decisão. |
| Backup e recuperação | D1 Time Travel oferece recuperação pontual com janela conforme o plano; restore sobrescreve o banco in-place, e cópia durável externa exige outro fluxo. Isso não substitui o backup cifrado atual nem foi exercitado por restauração sintética. | Retenção, backup e restauração dependem do datastore escolhido e da política de retenção; não avaliados. |
| Cobrança | A documentação oficial descreve camada gratuita e plano pago, limites de CPU/consultas, e custos de produtos associados. Limites locais por invocação não constituem um teto total de gasto. Nenhum gasto/cota de conta foi conferido. | Scale-to-zero não significa cobrança absolutamente nula: inicialização, encerramento e processamento de solicitações podem ser cobrados; instâncias mínimas mudam o perfil. A página documenta um “budget spend cap” como Preview; não foi habilitado nem provado como proteção efetiva. |
| Soberania/segurança | Região/jurisdição, identidade remota, isolamento, logs, quotas, rotação de segredos e threat model não selecionados. | Região, IAM, entrada, datastore, gestão de segredos, logs e threat model não selecionados. |

## Fatos documentais verificados

- Workers executa Python sobre Pyodide/WebAssembly; `threading` e `multiprocessing` não são funcionais no runtime e seu filesystem é efêmero.
- D1 suporta a maior parte do SQL SQLite, não o protocolo Python SQLite local. Consultas e serialização ficam sujeitas aos limites do Workers. Uma instância de banco D1 processa queries em série.
- Wrangler mantém uma tabela de migrações D1. Time Travel tem janela documentada e restaura o banco in-place; a disponibilidade e retenção dependem do tipo de armazenamento/plano.
- Cloud Run aceita workloads Python em containers, escala a zero por padrão, e usa filesystem gravável descartável por instância. Requisições podem esperar enquanto uma instância sobe.
- A documentação atual do Cloud Run diz que startup/shutdown também entram em cobrança request-based e descreve spend caps em Preview. Nenhuma proteção de custo foi testada na conta.

## Critérios antes de uma escolha

1. Revisar ameaça, autenticação remota, classificação de dados, jurisdição/região e política de retenção com o proprietário.
2. Converter apenas um banco sintético e rodar o conjunto de migrações/queries, conflitos de IDs, concorrência, revogação e backup/restore em cada adapter local.
3. Provar recuperação independente de qualquer restore in-place e limites de RPO/RTO com dados descartáveis.
4. Medir cold start, CPU, RAM, query latency e throughput nas regiões candidatas em experimento aprovado; comparar cargas e inatividade.
5. Identificar todos os serviços faturáveis, modelo de preço e suas dependências; provar hard quotas/budget alerts e testar um limite negado. Nenhuma camada gratuita é premissa do produto.
6. Fazer threat review independente antes de dados pessoais/institucionais ou acesso público.

## Fontes oficiais consultadas

- [Cloudflare Python Workers](https://developers.cloudflare.com/workers/languages/python/) e [pacotes Python](https://developers.cloudflare.com/workers/languages/python/packages/).
- [Runtime e biblioteca padrão Python Workers](https://developers.cloudflare.com/workers/languages/python/stdlib/).
- [SQL D1](https://developers.cloudflare.com/d1/sql-api/sql-statements/), [migrações](https://developers.cloudflare.com/d1/reference/migrations/), [limites](https://developers.cloudflare.com/d1/platform/limits/) e [Time Travel/backups](https://developers.cloudflare.com/d1/reference/time-travel/).
- [Limites e cobrança Workers](https://developers.cloudflare.com/workers/platform/limits/) e [preços Workers](https://developers.cloudflare.com/workers/platform/pricing/).
- [Visão geral Cloud Run](https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run), [contrato do container](https://docs.cloud.google.com/run/docs/container-contract), [billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings) e [otimização Python](https://docs.cloud.google.com/run/docs/tips/python).

## Decisão

Não escolher produção agora. Cloudflare não é um destino direto para o backend atual por causa do modelo Python Workers + bindings D1 não testados. Cloud Run é uma alternativa de contêiner mais próxima do runtime, mas exige armazenamento durável externo e controles de custo comprovados. Nenhuma plataforma, conta, chave ou faturamento foi ativado nesta sprint.
