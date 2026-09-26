# Demonstração reproduzível (5–10 minutos)

Use somente texto fictício, por exemplo `Nota fictícia de planejamento para teste.`. Nada aqui liga contas reais. Execute na worktree exclusiva. Dois terminais, com o mesmo hostname `127.0.0.1` no navegador e API.

1. Prepare uma frase local de 12+ caracteres de teste e um banco **novo fora do repositório**. No Terminal A:

   ```bash
   cd /Users/vic/.codex/worktrees/jarvis-overnight-unified-2026-09-26/Jarvis-Victor-OS/apps/api
   mkdir -p /tmp/jarvis-demo-manual-2026-09-26
   JARVIS_DATABASE_PATH=/tmp/jarvis-demo-manual-2026-09-26/memory.sqlite3 JARVIS_LOCAL_PASSPHRASE='frase-ficticia-local-2026' uv run --locked python serve.py
   ```

2. No Terminal B: `cd /Users/vic/.codex/worktrees/jarvis-overnight-unified-2026-09-26/Jarvis-Victor-OS/apps/web && npm run dev`. Abra `http://127.0.0.1:3000/integrado`, entre com a mesma frase. A UI indica API local sintética; Calendar continua simulado.
3. Em `/missoes`, crie uma missão sintética local com o nome `Planejamento fictício`. Abra `API local sintética`; clique `Conceder leitura e escrita de Missões (Escopo A)` — a concessão requer clique explícito. Clique `Prévia da importação`, depois `Confirmar envio`. A missão agora aparece na API; a cópia local permanece. Sem concessão/sessão, a leitura mostra 401/403.
4. Na seção `Selecionar fonte fictícia`, escolha a missão da API e um arquivo `.md` UTF-8 de até 50 KB com apenas a frase fictícia acima. Confira prévia/hash, marque a confirmação e clique `Registrar fonte sintética`. A fonte fica pendente. `Ver contexto autorizado` ainda a omite.
5. Clique `Conceder mission:review (Escopo A)`, atualize a fila, abra `Fonte sintética selecionada`, compare conteúdo e SHA, escolha `Aprovar rascunho` e confirme. O contexto ainda omite a fonte. Em `Conhecimento e contexto`, clique `Aprovar conhecimento` do registro selecionado. Agora `Ver contexto autorizado` mostra texto e ID da revisão de origem. Recarregue para observar decisões persistidas; o grant continua enquanto a API rodar.
6. Na missão da API, execute `run_next` para produzir artefato sintético e observar a revisão. Os testes automatizados também provam cancelamento/retry, resposta perdida, revogação e restauração após reinício com bancos temporários. Para examinar a jornada automática completa: `cd apps/web && npm run e2e -- --grep 'arquivo fictício escolhido'` (runner oficial).
7. Abra o `.app` local com `open -n -a /Users/vic/.codex/worktrees/jarvis-overnight-unified-2026-09-26/Jarvis-Victor-OS/apps/desktop/src-tauri/target/release/bundle/macos/JARVIS.app`. Ele demonstra navegação/captura **DEMO offline**, sem conexão com a API. **Não há APK** para abrir/instalar. Encerre os dois servidores manuais com Ctrl-C ao terminar; remova o banco temporário apenas se desejar apagar esses dados fictícios.

As capturas de seis larguras para `/missoes` e `/integrado` estão em `exports/nightly/2026-09-26/captures`; hashes em `EXPORTS_MANIFEST.json`.
