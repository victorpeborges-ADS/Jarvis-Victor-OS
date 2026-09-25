# Aprovações futuras — nada executado nesta sprint

Esta lista não pede confirmação para trabalho local já autorizado. São decisões explícitas necessárias antes de ultrapassar os limites sintéticos.

| Decisão/ação | O que deve ser aprovado antes |
|---|---|
| Encerrar Gate E | Auditoria independente read-only da branch/commit final e decisão formal do proprietário. Esta sprint não é aceite independente. |
| Usar dados reais | Conector, conta, categorias e domínios autorizados; finalidade, retenção, proveniência, backup, expurgo, compartilhamento e resposta a revogação. Não copiar dados restritos/saúde para memória pessoal. |
| Google/OAuth/Calendar/Gmail/Drive/GitHub | Provedor, escopos OAuth mínimos, conta/tenant, tipo de dados, consentimento e teste de revogação; nada foi conectado. |
| Cloud/hosting | Escolha entre alternativas e região/jurisdição; conta, recursos, exposição, IAM, segredos, datastore, backup, limites de cobrança e teste de bloqueio de gasto. Nenhum billing/recurso foi ativado. |
| LLM/handoff externo | Provider e ferramenta autorizados, dados que podem sair, minimização/retenção, controle de orçamento e revisão humana. ChatGPT Work só tem envelope manual; Mistral/Grok não foram conectados. |
| Remoto, túnel ou webhook | Threat model, identidade, TLS, regras de firewall, logging, quotas, resposta a incidente e aprovação separada para cada endpoint. Nenhum endpoint público criado. |
| macOS/Android nativos | Aprovação de instalação/provisionamento local de Rust/Cargo e Android Studio/SDK/Gradle se os toolchains não forem encontrados; permissões de dispositivo e qualquer Share Intent precisam de revisão própria. Scaffolds Tauri/Capacitor existem e os frontends web passaram; `.app` e APK ainda não existem, nem foram instalados/distribuídos. |
| Notificações, n8n ou automação | Scheduler/processo autorizado, canal, janela, interrupções e consentimento para cada efeito. O simulador atual não notifica nem opera em background. |

Não use estas linhas para presumir autorização: cada integração ou serviço mantém gate próprio. Nenhuma conta pessoal, chave/token, API paga ou dado pessoal foi acessado.
