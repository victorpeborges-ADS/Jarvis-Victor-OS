# ADR 004 — roteador fake e observadores locais

- Estado: aceito para simulação sintética isolada.
- Data: 2026-09-25.

## Decisão

O `IntelligenceRouter` oferece apenas `FakeProvider`, cuja resposta vem de uma regra determinística. O teto de custo é 0, a privacidade aceita pelo provider é `synthetic_only`, e classificações privadas/sensíveis/restritas usam fallback `no_llm` sem chamar provider. Um pacote para ChatGPT Work só é montado para revisão manual; a transmissão sempre é `manual_only`.

`FakeWorkflowAdapter` recebe alterações sintéticas, filtra grants antes do domínio, não altera a entrada e retorna `side_effects: []`. A política de notificação local respeita desativação, interrupções e janela silenciosa. A execução é chamada manual em teste; não há scheduler, n8n, webhook, bot, alerta externo ou promise de background.

## Consequências

- Esses adaptadores demonstram contratos sem tráfego a provedor e sem custo de API.
- Não são autorização para ChatGPT Work, Mistral, Grok, n8n, contas externas ou dados reais.
- Antes de conectar qualquer provider, adicionar consentimento explícito, política de minimização, classificação, orçamento, retenção e auditoria independente.
