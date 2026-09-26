# Revisão de segurança — branch noturna

**Classificação:** revisão própria, não laudo independente. O G5 congelado recebeu veredito FAIL em `G5_AUDIT.md`; correções permanecem somente nesta branch.

| Controle | Evidência | Estado residual |
|---|---|---|
| Identidade/CSRF/Origin/Host | Sessão local e grants de recurso+domínio; API loopback; testes negativos de origem e CSRF. | Sessões/grants apenas em memória de um processo. |
| Revogação durante decisão | Lock de grant e sessão cobre commit de decisão/revisão; probes de pausa/revogação. | Um GET autorizado antes da revogação pode terminar depois. |
| Snapshot e ledger | Snapshot por versão em 0010; hash canônico; triggers impedem UPDATE/DELETE diretos. | Operador com escrita total no SQLite ainda pode alterar arquivo/triggers; não há assinatura externa. |
| Conhecimento/contexto | Estágio separado; exige artefato íntegro e aprovado, depois decisão de conhecimento; leitura filtrada por proprietário/domínio/grant e orçamento. | Não há TTL por fonte, FTS ou política de retenção real. |
| Arquivo selecionado | Picker explícito, extensão/nome/UTF-8/50 KB/hash, confirmação fictícia, chave idempotente, transação; banco sintético temporário no teste. | Checkbox não prova que o conteúdo é realmente fictício; uso pessoal verdadeiro requer novo gate. |
| Isolamento DEMO/API | Datasets e stores separados; sem fallback silencioso; E2E confirma. | O usuário pode copiar texto manualmente; classificação de conteúdo não automatizada. |
| Segredos/logs | Sem novas credenciais, OAuth ou chaves; `git` não inclui builds/temp; não houve outbound LLM. | Auditoria profunda de dependências e varredura formal de segredos não concluídas. |
| MCP/tool injection | Nenhum servidor MCP, cliente ou ferramenta de terceiro foi instalado. | Registry/allowlist MCP ainda por implementar antes de ativação. |
| Segundo worker/nuvem | Nenhum; SQLite e locks locais inviabilizam alegar consistência distribuída. | Exige arquitetura e autorização novas. |

**Probes G5:** logout entre leitura/commit; grant de escrita revogado antes da revisão; decisões incompatíveis; replay alterado; versão antiga; corrupção; rollback; SIGKILL antes/depois; restore cifrado. Resultados e falhas no snapshot original em `G5_AUDIT.md`. O caminho noturno tem regressões específicas e API completa 192/192.

**Riscos abertos visíveis:** aceite formal G5 pendente; sessão/grant voláteis; conteúdo selecionado pode conter dado real se o operador ignorar a classificação; API sem autenticação remota; nativos não têm storage seguro/API. Nenhuma versão da branch noturna deve ser apresentada como pronta para conta pessoal ou produção.
