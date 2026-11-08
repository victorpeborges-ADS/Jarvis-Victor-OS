# JARVIS — protocolo de continuidade entre conversas

**Versão:** 1.0 · **Data:** 2026-11-07 · **Escopo:** JARVIS Victor OS.
**Regra superior:** `AGENTS.md`, contratos de segurança e decisões de aceite existentes prevalecem. Este documento não concede novas permissões.

## Propósito

O chat é uma sessão de trabalho temporária, não a fonte de verdade. O objetivo é permitir retomar uma implementação em nova conversa sem arrastar logs, código, anexos e respostas completas de ferramentas. Não há mecanismo confiável neste repositório para medir automaticamente o espaço restante no contexto do ChatGPT.

## Fontes e fronteiras

1. **Git, código e documentação de gates:** fonte do estado técnico versionado. Confirmar `branch`, `HEAD`, `git status` e evidências antes de agir. Logs de testes antigos não equivalem a nova execução.
2. **`AGENTS.md` e documentação de aceite:** contratos e limites de autorização. A existência de um plano não autoriza sua execução.
3. **Checkpoint técnico vivo:** `docs/CHECKPOINT_ATUAL_JARVIS.md`; resumo verificável e enxuto, não cópia integral de histórico. Atualizar somente após checar fontes.
4. **Contexto pessoal/operacional privado:** permanece no Google Drive autorizado (pasta *Memoria GPT*) e nas fontes apropriadas, nunca neste repositório público.
5. **Friday:** é um aplicativo/projeto separado do JARVIS. Não usar este checkpoint como prova de build, testes, estado ou permissões da Friday.

Quando as fontes divergirem, **não inventar conciliação**: apontar divergência, evidência, timestamp e estado `NÃO VERIFICADO`; priorizar código e testes efetivamente inspecionados.

## Gatilhos de checkpoint

- Após um marco, uma execução de agentes, uma mudança de gate, ou uma decisão relevante.
- Antes de encerrar uma conversa, migrar de chat/agente, substituir piloto ou trocar de máquina.
- Preventivamente após várias interações técnicas com logs extensos (sugestão operacional: revisar após 10–20 trocas intensas; não é cota fixa nem medição de tokens).
- Sempre que o histórico estiver confuso, resumir *antes* de continuar com mais ferramentas.

## Checkpoint obrigatório: estrutura máxima recomendada de 400–800 palavras

```md
# CHECKPOINT VIVO — <projeto> — <data/hora com fuso>
Estado do registro: VERIFICADO | PARCIAL | DESATUALIZADO
BASELINE: repositório, branch, SHA, versão, ambiente e data da verificação
OBJETIVO: uma frase e escopo autorizado
ESTADO: IMPLEMENTADO | TESTADO | PROPOSTO | BLOQUEADO | NÃO VERIFICADO
ARTEFATOS: arquivos e links para evidência (não colar conteúdo integral)
TESTES: comando, PASS/FAIL/BLOCKED, data, condições e origem
DECISÕES: o que mudou, por quê, o que foi descartado
TRABALHO LOCAL: modificados/não rastreados e risco de sobrescrita
RISCOS: segurança, custos, privacidade, consentimento e pendências
PRÓXIMA AÇÃO: uma tarefa executável com critério de sucesso
FONTES: links para AGENTS.md, roadmap, handoffs e docs canônicos
```

O handoff operacional deve também atender à seção **Handoff obrigatório** de `AGENTS.md`: BASELINE, OBJETIVO, ARQUIVOS ALTERADOS, DECISÕES, COMANDOS EXECUTADOS, TESTES PASS/FAIL/BLOCKED, CAPTURAS/DEMOS, RISCOS RESIDUAIS, PENDÊNCIAS DE AUTORIZAÇÃO e PRÓXIMO GATE. O checkpoint é um índice compacto; o handoff detalhado continua na documentação adequada.

## Ciclo de trabalho

1. **Abrir:** ler `AGENTS.md`, checkpoint atual e documento da etapa; verificar Git e ambiente, confrontar com o que foi registrado.
2. **Executar:** manter uma frente por vez e retornar sínteses em vez de despejar logs; guardar links para resultados e artefatos completos.
3. **Fechar:** coletar arquivos alterados e testes, classificar cada afirmação, atualizar o checkpoint e os docs canônicos sem duplicar conteúdo.
4. **Verificar gravação:** reler arquivo/destino persistido, conferir SHA/revisão, deixar evidência da mudança.
5. **Retomar:** iniciar novo chat com o prompt abaixo; a continuidade é orientada por fontes, não por alegação de memória integral.

## Prompt de retomada (copiar em um novo chat)

> Continue o **JARVIS Victor OS**. Consulte `AGENTS.md`, `docs/PROTOCOLO_CONTINUIDADE_CONVERSAS.md` e `docs/CHECKPOINT_ATUAL_JARVIS.md`, além do roadmap e do handoff apontados nesses arquivos. Reconcilie com `git status`, branch e commit atuais; não presuma que uma proposta foi implementada nem que testes antigos foram repetidos. Preserve alterações não commitadas, worktrees, backups, dados privados e limites de autorização. Informe BASELINE, confirmações, divergências, bloqueios e primeiro passo seguro. Ao concluir, atualize o checkpoint verificando sua persistência.

## Regras de economia de contexto e segurança

- Não copiar dumps de terminal, código inteiro, dados sensíveis, anexos duplicados, chaves, cookies, conteúdo pessoal ou institucional para chat/checkpoint.
- Resumir retorno de agentes em: resultado, arquivos modificados, testes, erros que importam, evidências, próximos passos.
- Usar links para fontes e selecionar apenas trechos necessários. Para alterações novas, conferir diretamente os arquivos.
- Nunca declarar `PASS`, implantação, conexão real, autonomia contínua ou custo zero sem evidência específica.
- Nenhum checkpoint autoriza push, deploy, acesso remoto adicional, envio externo, dados reais, operações destrutivas ou cobrança. Aplicam-se as aprovações de `AGENTS.md`.
- Não afirmar que a troca de conversa é automática: as fontes persistem, mas a nova sessão deve ser iniciada e verificada.
