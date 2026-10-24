# ADR-014 — Push-to-talk local fica bloqueado nesta consolidação

- Status: contrato de estado em 22/10/2026. Microfone, Speech, observação de tela e smoke da janela continuam bloqueados.
- Date: 2026-10-17.
- Supersedes: none.

## Dependência

O único caminho local de áudio inspecionado está fora desta candidata:

- worktree `/Users/vic/.codex/worktrees/jarvis-voz-ptt-audio-20261012/Jarvis-Victor-OS`
- branch `feat/jarvis-voz-ptt-audio-local`
- HEAD `06a9ba0b14584a4fff5f3a8ed2b37b47717f8970`, com alterações locais não commitadas
- `LIVE_VOICE_CAPTURE_ENABLED` permanece `false` em `apps/desktop/src-tauri/src/runtime_manager.rs` dessa worktree

Os comandos de pressionar, consultar, concluir e soltar devolvem o gate do proprietário e não abrem captura. O helper consulta o estado de Speech e de microfone; não chama `requestAuthorization` nem `requestAccess`. A revisão de 13/10/2026 dessa worktree também deixa em aberto o monitoramento de foco durante `LISTENING` e o corte autônomo de 30 segundos.

Na candidata, `lib.rs`, `App.tsx`, `runtime_manager.rs` e `native_app_api.py` já estão modificados por outras frentes. Integrar o helper Swift exigiria reescrevê-los.

## Critério de aceite

Uma subentrega futura mostra, na própria candidata, os estados iniciando, ouvindo, processando, falha e cancelado. O microfone só abre depois de um gesto explícito, em primeiro plano, com indicador visível. Não há wake word nem escuta contínua. A transcrição não envia efeito. Cancelar não grava captura. O smoke da janela e o teste acústico continuam um gate separado.

## Motivo do bloqueio

O caminho de áudio não está nesta árvore, e o gate dessa outra árvore está fechado. O escopo não é uma subentrega pequena com dependências já resolvidas aqui. Wake word, escuta contínua, câmera, observação de tela e gestos continuam de fora.

## Contrato de estado em 22/10/2026

`apps/api/voice_session.py` guarda os estados na candidata, sem integrar o helper Swift da outra worktree e sem alterar `lib.rs`, `App.tsx` ou `runtime_manager.rs`. O microfone não abre. Wake word permanece desligada e não aprova efeito. A transcrição não envia mensagem. Cancelar não grava captura. Observação de tela e ação nativa devolvem BLOCKED. Áudio real e smoke da janela continuam NOT TESTED.

## Próximo gate

Autorização explícita do proprietário para Speech e microfone, correção do foco e do limite de 30 segundos na worktree de voz, e uma integração que não sobrescreva os arquivos já sujos da candidata. Até lá o áudio real e o smoke da janela ficam BLOCKED. Áudio real desta verificação: NOT TESTED.
