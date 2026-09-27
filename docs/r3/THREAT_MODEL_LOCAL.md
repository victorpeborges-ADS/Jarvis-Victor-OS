# Modelo de ameaças — integração local do JARVIS

**Escopo:** Gate 2.0-E / sprint R3, serviço FastAPI local e interface no mesmo aparelho. Este documento descreve o limite de segurança que o código atual consegue sustentar; não constitui aceite formal de G5.

## Ativos e limites de confiança

- Sessão local, concessões por recurso/domínio, conteúdo de missões, revisões, fontes e registros de auditoria.
- A API recebe somente conexões de loopback e a interface recusa destinos fora de loopback. A política de origem, `SameSite=Lax`, validação CSRF nas mutações e sessão `HttpOnly` complementam esse limite.
- As concessões e sessões existem apenas na memória de um processo. O banco SQLite local é separado das fixtures públicas de demonstração; para esta sprint, testes usam bancos sintéticos temporários.
- A agenda consumida no Gate D e as fontes adicionadas nos ensaios são fictícias. Não há OAuth, serviço remoto, autenticação por grant fora do aparelho ou escrita em contas reais.
- `domain_id` seleciona o escopo de uma concessão e nunca autoriza acesso por si só. Dados da demonstração no navegador e dados da API local são domínios separados.

## Atores e ameaças consideradas

1. **Página externa ou origem cruzada:** tenta ler conteúdo, explorar o navegador em loopback ou enviar mutações sem autorização.
2. **Código local sem concessão compatível:** tenta consultar outra área, usar inventário de calendário como leitura de eventos ou continuar após revogação/expiração.
3. **Corrida concorrente de leitura e revogação:** uma leitura valida a concessão, perde a corrida para uma revogação e depois monta/retorna dados como se ainda estivesse autorizada.
4. **Repetição ou concorrência de mutações:** repete importações, mudanças de estado, revisões ou decisões com estado/versão obsoletos.
5. **Falha de armazenamento ou encerramento:** causa perda, corrupção, restauração ou substituição do banco local.
6. **Processo/host mal configurado:** tenta expor a API na rede, compartilhar concessões entre workers ou tratar a sessão local como identidade remota.

## Controles implementados e invariantes

- O servidor valida loopback, origem e cabeçalho `Sec-Fetch-Site`; mutações também exigem origem permitida e token CSRF da sessão. A interface permite apenas APIs no loopback.
- As rotas de Missões confirmam a sessão e a concessão `mission:read` antes de obter snapshots. GET de revisões aceita somente domínios autorizados por `mission:read` ou `mission:review` conforme o contrato da rota. O conjunto de domínios permitido é usado para filtrar/validar o snapshot retornado.
- A revalidação fica protegida por `_grant_lock` enquanto o repositório lê e copia o resultado. Revogações usam o mesmo lock: uma revogação que ganha primeiro faz a leitura seguinte falhar com 403; uma leitura que ganha primeiro termina seu snapshot antes de a revogação prosseguir.
- **Ordem obrigatória de locks:** `_grant_lock` → transação/leitura SQLite. Código não pode adquirir `_grant_lock` de dentro de uma transação SQLite. A ordem evita deadlock e mantém a decisão de autorização linearizável em relação à revogação.
- Mutação continua exigindo revalidação no servidor, idempotência e versão esperada. O servidor rejeita uma decisão baseada em ID/versão anterior; a interface passa a acompanhar o novo ID de revisão retornado por `revise`.
- Sessões e grants são voláteis, expirados/revogados deixam de autorizar novas operações, e os grants são escopados a principal, recurso e domínio. A inicialização segue em processo único.
- Os probes de R3 cobrem as duas ordens concorrentes para listagem e detalhe de missão e de revisão: leitura segura primeiro e revogação primeiro. As rotas de escrita mantêm os probes existentes de conflito e autorização.

## Limites e riscos residuais

- Uma leitura autorizada que vence a corrida pode ter seu corpo entregue pelo servidor depois que a revogação aguardada termina: a aplicação garante que o snapshot foi selecionado e copiado antes da revogação, não que bytes já autorizados sejam apagados de buffers ou da rede local. Nenhuma leitura nova iniciada após a revogação passa pelo guard.
- Quem controla a conta do sistema operacional pode ler/alterar os arquivos locais e substituir o banco. As concessões da aplicação não protegem contra um administrador do mesmo host.
- SQLite e UI são locais, não cifrados por esta sprint; retenção, restauração operacional, backup e resistência a malware não são alegados.
- Execução com mais de um worker/processo, acesso remoto, túnel, OAuth, contas reais, replicação de sessão/grants e deploy público ficam fora do modelo e não são suportados.
- O aceite de G5 permanece pendente de auditoria independente. Esta sprint documenta e testa os controles, sem declarar esse gate formalmente aceito.

## Evidência de regressão prevista

Registrar no relatório R3 o resultado integral de `uv run --locked pytest -q`, os probes direcionados de G4/G5/R2 e `test_mission_read_revocation_races.py`. A evidência vale para os dados sintéticos descartáveis usados pelos testes, não para uma implantação remota ou produção.
