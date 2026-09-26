# Decisões e autorizações pendentes

Nenhuma ação abaixo foi executada nesta operação. O pedido atual autoriza implementação e teste local sintético; as decisões abaixo exigem autorização específica.

| Decisão | Material preparado | Ação após aceite |
|---|---|---|
| G5 e branch noturna | `G5_AUDIT.md`, testes/commits/relatórios | Auditor distinto revisa snapshot; proprietário decide aceite e eventual merge. |
| OAuth Calendar pessoal | Calendar simulado e contrato de grants | Escolher escopos, conta, calendário e política de retenção; então implementar conexão real. |
| Gmail, Drive/Docs, Contacts, GitHub | Matriz de capacidades | Autorizar por serviço, recurso, domínio e finalidade antes de leitura. Escrita externa por operação. |
| Dados pessoais por fonte | `CONTEXT_ONBOARDING.md` e picker sintético | Aprovar classificação, armazenamento seguro, consentimento, retenção/exportação/remoção. |
| Toolchain Android | Diagnóstico: sem Java Runtime/SDK | Instalar JDK/SDK e aceitar licenças; gerar APK debug e testar em emulador. Instalação no telefone exige aceite adicional. |
| Distribuição macOS | `.app` local x86_64 sem assinatura | Apple Developer ID, assinatura/notarização e eventual `.dmg` de distribuição. |
| Publicação Android | APK ainda não existe | Assinatura release, Play Console e políticas de loja após QA. |
| SDK/MCP/LLM externo | Contratos existentes, lacunas mapeadas | Aprovar novos pacotes/licenças e provedor, orçamento e dados permitidos. |
| Hospedagem remota/multiworker | `ARCHITECTURE_AND_MODULE_MAP.md` | ADR de banco, auth, quotas, custo e revogação; só depois PoC remota. |
| Push/tag/merge | Worktree exclusiva, commits locais | Solicitação separada; `main` e candidata G5 preservadas. |

**Pedido imediato mínimo:** revisor independente para os achados G5 e decisão sobre continuidade da candidata corrigida. Nenhum bloqueio de autorização impediu os testes locais e a documentação.
