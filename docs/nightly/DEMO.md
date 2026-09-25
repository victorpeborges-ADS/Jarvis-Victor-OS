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

O E2E completo que demonstra a integração sintética browser/API é `rtk env JARVIS_E2E_WEB_ORIGIN='http://[::1]:3000' JARVIS_E2E_API_ORIGIN='http://[::1]:8000' JARVIS_E2E_SCREENSHOT_DIR='/tmp/jarvis-e2e-captures' npm run e2e` a partir de `apps/web`; ele cria seu banco temporário, comprova a identidade da API iniciada e encerra os serviços próprios. A UI só consulta o catálogo após existir grant ativo; o servidor filtra calendários classificados fora do escopo.

Se a recuperação local encontrar Missões inválidas, a página mantém as entradas válidas, isola o material rejeitado e permite baixar um pacote JSON para revisão manual ou descartar a cópia isolada.

## Capturas

- [Missões desktop](captures/missions-desktop.png)
- [Missões mobile](captures/missions-mobile.png)
- [Integração sintética desktop](captures/gate2-e-integrado-desktop.png)
- [Integração sintética mobile](captures/gate2-e-integrado-mobile.png)

Todas as capturas foram feitas no Playwright com dados fictícios. O modo API sintético não é modo DEMO e a Central de Missões não lê nenhum dos dois datasets.

## Scaffolds nativos, sem `.app` ou APK

- Desktop web-shell: em `apps/desktop`, execute `rtk npm run dev`; Vite está preso a `127.0.0.1:1420`. Agora/Conversa/Missões alternam entre textos ilustrativos locais. A janela Tauri não é iniciada sem Rust/Cargo.
- Android web-shell: em `apps/mobile`, execute `rtk npm run dev -- --host 127.0.0.1`; navegue para `http://127.0.0.1:5173`. Em Inbox, salve uma captura fictícia e recarregue para conferir a outbox local. O E2E desta shell cobre desktop e mobile; não é APK.
