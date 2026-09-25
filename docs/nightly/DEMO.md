# Demonstração local — Central de Missões sintética

## Pré-condições

- Abra a worktree noturna, não o checkout original.
- Instalação do frontend já foi feita com `npm ci`.
- O fluxo de Missões não depende da API; o banner informa que usa `localStorage`, 100% sintético, custo zero e sem escrita externa.

## Roteiro manual

1. Em `apps/web`, execute `rtk npm run dev -- --hostname 127.0.0.1` e navegue para `http://127.0.0.1:3000/missoes`.
2. Confirme o banner `SIMULAÇÃO · 100% SINTÉTICA` e a indicação de armazenamento somente neste navegador.
3. Crie uma missão chamada, por exemplo, “Revisar fontes fictícias”, no domínio sintético A.
4. Execute cada etapa simulada. Confira que aparecem três etapas encadeadas, checkpoints e eventos, um pacote de contexto sintético e um rascunho com referências de proveniência.
5. Abra “Revisar fontes e decisão”; marque o rascunho aprovado para uso local. O texto confirma que nada foi enviado ou publicado.
6. Recarregue a página: a missão reaparece por armazenamento local do navegador. Limpar o perfil remove essa simulação.
7. Opcionalmente crie outra missão, pressione “Demonstrar falha/retry”, prepare o retry local e cancele. Não há execução externa.

O E2E completo que demonstra a integração sintética browser/API é `rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' npm run e2e` a partir de `apps/web`; ele cria seu banco temporário e encerra os serviços iniciados por ele.

## Capturas

- [Missões desktop](captures/missions-desktop.png)
- [Missões mobile](captures/missions-mobile.png)
- [Integração sintética desktop](captures/gate2-e-integrado-desktop.png)
- [Integração sintética mobile](captures/gate2-e-integrado-mobile.png)

Todas as capturas foram feitas no Playwright com dados fictícios. O modo API sintético não é modo DEMO e a Central de Missões não lê nenhum dos dois datasets.
