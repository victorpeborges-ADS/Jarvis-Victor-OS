# JARVIS Gate 2.0-D — aceite independente

## Decisão e escopo

O Gate 2.0-D está tecnicamente aceito para o adaptador Google Calendar inteiramente simulado e para o uso de bancos sintéticos temporários. A branch `fix/gate2.0-d1-calendar-hardening`, commit `3175c0feb4da60aa9ad1cdf6d9d74e5aa7d9c513`, foi incorporada à `main` por fast-forward. A tag anotada local `gate2-d-accepted-v0.1` aponta exatamente para esse commit. Este registro foi adicionado em commit documental separado.

O aceite não autoriza OAuth, conexão com Google, dados pessoais ou institucionais, Gmail, Drive, deploy ou acesso remoto. As fixtures DEMO permanecem separadas da memória SQLite.

## Evidências da auditoria independente

A auditoria independente reportou os seguintes resultados para o incremento D.1:

| Verificação externa relatada | Resultado |
|---|---|
| Suíte da API | PASS — 136 testes |
| Probes adversariais adicionais | PASS — 7 probes |
| Vitest | PASS — 31 testes |
| CORS e classificação por PUT em HTTP/socket real | PASS, conforme auditoria |
| Revogação concorrente, reconciliação de snapshot completo e epoch do provider | PASS, conforme auditoria |

Os 7 probes adversariais pertencem à evidência produzida pela auditoria e não são apresentados como testes versionados neste repositório. Os testes implementados no projeto estão descritos em [handoff D.1](GATE2_0D_1_HARDENING.md) e [documentação do simulador](GATE2_0D_CALENDAR_SIMULADO.md).

## Riscos e limites remanescentes

- A coordenação de grants usa lock em memória e é válida somente para um processo/worker da API.
- Um GET cuja decisão de autorização ocorreu antes da revogação pode responder depois; bytes já serializados/enviados não podem ser recolhidos. Leituras iniciadas após a revogação continuam sujeitas à autorização do servidor.
- Eventos de dia inteiro não são suportados. A semântica de datas inclusivas/exclusivas e fuso precisa ser especificada antes de qualquer integração real.
- O provider é simulado; os estados da aplicação não significam que uma conta Google esteja conectada.
- Nenhum dado pessoal/institucional ou OAuth está autorizado por este aceite.

## Próximo passo

Está autorizado iniciar o Gate 2.0-E para integrar a interface com a API local usando exclusivamente o provider e dados sintéticos. O Gate E requer revisão independente antes de qualquer consolidação. Nenhuma conexão externa ou uso de dados reais é abrangido.
