# Contrato comum de cliente

## Regra de autoridade

Web, macOS e Android são clientes de apresentação. O Victor OS API é autoridade para sessão autenticada, autorização, grants, domínio, estado de missão, revisão/approval, proveniência, conhecimento confiável, contexto, skills e artefatos. O cliente pode ocultar uma ação para UX; isso nunca substitui a recusa do servidor. O servidor deve rejeitar comando sem sessão, grant, domínio ou versão válidos mesmo que um cliente adulterado envie a chamada.

## Fonte e geração de tipos

- Modelos Pydantic e OpenAPI da API são a fonte canônica de request/response.
- A Web atual possui tipos manuais em `apps/web/lib/local-api.ts`; eles não são uma segunda política de autorização.
- Não criar nesta sprint `packages/jarvis-client`, `packages/contracts` ou `packages/ui-contracts`.
- No G6.1, gerar ou validar tipos TypeScript a partir do OpenAPI e usar o resultado em pelo menos Web Integrado e macOS. Manter gerador reproduzível, schema versionado e verificação de drift no CI.
- Um wrapper de transporte comum só se justifica quando houver dois clientes conectados. Ele pode tratar serialização, cookies/CSRF, correlation ID e erros; não deve conter regra de autorização ou uma segunda máquina de grants.
- Não compartilhar componentes visuais React como obrigação entre Next.js e Capacitor/Tauri. Contrato de API e design tokens podem ser compartilhados sem acoplar navegação ou runtime.

## Forma de chamada

O cliente envia comando tipado para o endpoint definido no OpenAPI. Não compõe SQL, decide escopo nem infere origem de dados pela acessibilidade da rede. Para chamadas autenticadas:

1. usar HTTPS somente se houver terminador local confiável definido; hoje o runner loopback usa HTTP, então a segurança do G5 não afirma proteção criptográfica contra outros processos do mesmo usuário;
2. enviar cookie de sessão de acordo com SameSite e origin permitidos;
3. incluir CSRF nos métodos mutáveis conforme o contrato atual;
4. se G6.1 adicionar correlation_id por chamada, validar tamanho/alfabeto no servidor e gerar um quando ausente; o contrato atual usa IDs de correlação em eventos de missão, não define um header comum para toda request;
5. usar idempotency_key onde o contrato de operação exigir;
6. comandos condicionais incluem expected_revision ou hash esperado; conflito exige recarregar estado e não repetir cegamente;
7. tratar 401, 403, 404, 409, 422 e 5xx como estados distintos, preservando mensagens seguras e sem revelar conteúdo indevido.

Os caminhos da API atual não têm prefixo de versão. Antes de o macOS conectar, G6.1 precisa congelar OpenAPI, decidir convenção de versionamento e definir política de breaking change. Não renomear rotas nesta sprint.

## Erros comuns de aplicação

| Código/categoria | Significado para a interface | Próxima ação |
|---|---|---|
| `session_required` / HTTP 401 | Não há sessão válida ou ela expirou/reiniciou junto com processo. | Mostrar “Sessão encerrada”; pedir autenticação explícita; não reciclar grants locais da memória do cliente. |
| `grant_missing` / HTTP 403 | O servidor negou o recurso/domínio solicitado. | Mostrar domínio e permissão ausentes sem tentar ampliar escopo. |
| `not_found` / HTTP 404 | O recurso não existe ou não é visível nesse escopo. | Não confirmar a existência em outro domínio. |
| `revision_conflict` / HTTP 409 | Missão, artefato ou decisão mudou desde a leitura. | Buscar estado atual, destacar mudança e exigir nova ação humana se aplicável. |
| `validation_error` / HTTP 422 | O comando não corresponde ao contrato. | Corrigir formulário; preservar rascunho local se seguro. |
| `database_unavailable` / HTTP 503 | SQLite ou runtime não está pronto. | Estado degradado; não mudar para DEMO, não fazer retry mutável automático. |
| `backend_unreachable` | Falha de transporte, processo encerrado ou endpoint inválido. | “Victor OS indisponível”; retry só por ação controlada e com backoff. |

As strings são categorias semânticas propostas. A implementação deve mapear o formato de erro FastAPI atual para uma união tipada sem expor exceções ou stack traces.

## Tipos semânticos de estado

```ts
// Projeção de interface: mapear dataset legado + provider_mode + provenance.
type Dataset = "demo" | "api_synthetic" | "future_authorized";
type Connectivity = "starting" | "ready" | "degraded" | "offline";
type SessionState = "unknown" | "anonymous" | "authenticated" | "expired";
type GrantState = "unknown" | "missing" | "active" | "expired" | "revoked";
type MissionState =
  | "queued" | "running" | "waiting_approval" | "blocked"
  | "completed" | "failed" | "cancelled";
type ApprovalState =
  | "pending" | "approved" | "rejected" | "changes_requested"
  | "superseded" | "unavailable";
```

Os nomes são vocabulário de interface, não uma licença para armazenar ou inferir estado autoritativo no cliente. Estado local cacheado deve carregar timestamp e rótulo stale; uma resposta atual do servidor substitui a projeção do cliente.

### Invariantes de estado

- `DEMO` é um dataset escolhido e indicado, não um fallback de erro.
- O valor legado `dataset="real"` nas rotas atuais identifica o caminho da API local; quando provider_mode é simulated, a interface deve dizer “API local · dados sintéticos”.
- `Starting` só termina em `Ready` após handshake com o processo esperado, resposta de prontidão e banco disponível.
- `Degraded` informa capacidade reduzida com causa legível; `Offline` não promete sincronização pendente.
- `Session expired` apaga credenciais transitórias em memória e volta a pedir autenticação.
- `Grant missing` é decisão do servidor, não toggle do cliente.
- `Approval` pendente pertence a uma revisão e versão de artefato específicas. Se mudou, atualizar a tela e solicitar nova decisão.
- A UI nunca afirma “salvo no JARVIS” para uma captura guardada apenas em localStorage.

## UX equivalente entre clientes

| Área canônica | Web | macOS | Android | Voz |
|---|---|---|---|---|
| Agora | Resumo do estado/API com proveniência | Janela principal e resumo de runtime | Tela inicial curta com conexão e estado local | Resposta breve; pode abrir tela correspondente |
| Conversa | Jornada atual com respostas e fontes; persistência compartilhada ainda não existe | Mesma API somente após G6.1; conversa local deve rotular escopo | Shell local em G6.3; continuidade só depois de G6.4 | Entrada/saída efêmera que usa a conversa aprovada |
| Inbox | Capturas e origem explícita | Capturas integradas após API; até lá localStorage claramente local | Outbox local até política de sync aprovada | Ditar pode criar rascunho; salvar segue confirmação e escopo |
| Domínios | Grant e classificação expostos pela API | Mesma lista/semântica depois de sessão | Explicação de indisponibilidade enquanto offline | Consultar em voz; concessão é administrada na UI |
| Aprovações | Fila persistente com versão e motivo | Mesma decisão do servidor | Somente fila local conectada após G6.4 | Pode anunciar e abrir; decisão final na revisão visível |
| Fontes | Proveniência e estado confiável | Proveniência e estado confiável | Sem fontes do aparelho sem seleção explícita e gate | Resposta cita origem de forma concisa; detalhe na tela |
| Missões | CRUD/transições validadas no servidor | Mesma missão após G6.1 | Sem missão compartilhada em G6.3 offline | Pode criar/consultar intenção; transição protegida precisa grant |
| Integração | Estado de fonte, mock, simulado ou erro | Runtime, processo, API e dataset em separado | “Sem sync configurado” até decisão | Sem comandos para conectar conta real |

Navigation no macOS usa rail/atalhos e janela desktop; Android usa navegação inferior para destinos principais e “Mais” para Fontes/Integração; Web preserva navegação existente. A nomenclatura e estados do produto devem permanecer iguais em PT-BR e acessíveis por teclado/leitor de tela.

## Versionamento e compatibilidade

**Contrato proposto para G6.1:** registrar OpenAPI produzido pelo build da API; gerar client TypeScript; validar schema em CI e em cada cliente; cada versão do .app anuncia a faixa de schema suportada. Servidor recusa client incompatível com erro claro. Compatibilidade é por contrato e não por confiar em versão de UI para autorização.

Forma final (prefixo `/v1`, header ou ambos) permanece pendente de decisão após inspeção do tráfego real do Tauri WebView. Ver [DECISIONS_PENDING.md](DECISIONS_PENDING.md), item DEC-06.
