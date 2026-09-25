# ADR 002 — runtime da Central de Missões em modo sintético

- Estado: aceito somente para demonstração local.
- Data: 2026-09-25.

## Decisão

A primeira Central de Missões roda no navegador e persiste somente em `localStorage` sob `jarvis.synthetic.missions.v1`. A execução é composta por regras TypeScript determinísticas com quatro manifests versionados. O teto de custo é fixo em zero. Artefatos permanecem como rascunhos locais e exibem origem/versão da skill. A decisão sobre um rascunho é uma marca local reversível e não aciona publicação.

O montador de contexto recebe um conjunto explícito de IDs concedidos e aplica essa verificação antes de domínio/projeto, frescor, validade e orçamento de bytes. Conteúdo de fonte fica em uma posição citada como dado e não é executado como instrução. Para dados reais, a API deve voltar a verificar grants e escopo; a verificação do cliente não é autoridade.

## Limites operacionais

- `localStorage` não oferece transação multiaba nem sincronização entre dispositivos; a atualização atual é síncrona somente dentro de uma aba/processo. Concorrência multiaba, restauração durável e revogação real seguem bloqueadas antes de memória real.
- A experiência não lê a API Gate E, fixtures DEMO, SQLite ou provedores externos.
- Retentativas apenas repetem funções puras locais; não existem efeitos externos para compensar.
- O fluxo de aprovação grava a escolha local do usuário no artefato. Nenhuma publicação acontece.

## Consequências

O fluxo pode ser testado e demonstrado sem misturar datasets. Antes de ativar persistência compartilhada, mover contexto para a API e introduzir provedores, será necessária auditoria própria de autorização, concorrência, recuperação e consentimento.
