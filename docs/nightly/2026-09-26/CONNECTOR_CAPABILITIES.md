# Capacidades de conectores — estado em 26/09/2026

| Conector | Estado | Capacidade provada | Custo/limite e próximo passo |
|---|---|---|---|
| Calendar simulado | TESTADO LOCALMENTE / MOCK | Provider sintético do Gate D, grants e leitura local; nenhum Google Calendar real. | Custo externo zero. OAuth/calendar real depende de gate e escopos aprovados. |
| Gmail | NÃO CONFIGURADO | Nenhuma leitura, busca, envio ou rascunho real. | Escopos sensíveis, política de dados e autorização específica antes de adapter. |
| Drive/Docs | NÃO CONFIGURADO | Nenhum arquivo pessoal/institucional acessado. | Seleção explícita e classificação antes de OAuth. |
| Contacts | NÃO CONFIGURADO | Nenhum contato acessado. | Escopo mínimo e finalidade a aprovar. |
| GitHub pessoal | NÃO CONFIGURADO | Nenhum repositório externo lido/escrito. | Selecionar repos e recursos; ações de escrita exigem aceite por operação. |
| Arquivo local sintético | TESTADO LOCALMENTE | Picker web explícito, UTF-8 .txt/.md/.json até 50 KB, SHA-256, revisão dupla e contexto com citação. | Sem varredura de disco. Dados reais bloqueados por política/consentimento. |
| MCP | NÃO CONFIGURADO | Nenhum servidor/cliente MCP operacional. | Registry, trust, allowlist e testes antes de habilitar. |
| LLM/roteador | NÃO CONFIGURADO | Nenhuma chamada outbound LLM foi implementada na branch. Skills atuais são determinísticas. | Cap de custo externo zero; orçamento e provedor dependem de decisão. |
| n8n | NÃO CONFIGURADO | Nenhum webhook ou executor ativo. | Política, callback idempotente e autorização futura. |
| ChatGPT Work/CLIs | NÃO CONFIGURADO | Apenas handoff documental deste repositório. | Sem automação de conta/CLI externa. |

Estados `CONECTADO REAL`: **nenhum**. Catálogo persistido de capabilities, wizard OAuth, adapter Gmail/Drive/GitHub, MCP STDIO e router FakeProvider permanecem pendentes. O material em `APPROVAL_REQUESTS.md` separa decisões do proprietário.
