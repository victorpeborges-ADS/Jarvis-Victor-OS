# Edição matinal JARVIS — 26/09/2026

| Classe | Entrega real |
|---|---|
| ENTREGUE E TESTADO | Correções G5 na branch noturna; Missão sintética → artefato → decisão humana persistente → conhecimento aprovado separadamente → contexto com citação; seleção manual de arquivo fictício `.txt/.md/.json`; web e shell macOS offline. |
| ENTREGUE MAS NÃO TESTADO | Navegação detalhada do `.app` por automação GUI; conexão nativa com API inexistente. |
| MOCK/DEMO | Calendar simulado, fontes/skills sintéticas, shells macOS/Android em DEMO offline. Nenhuma conta real conectada. |
| BLOCKED | APK debug **NÃO GERADO**: falta Java Runtime e Android SDK. `.dmg` **NÃO GERADO**. |
| REQUER APROVAÇÃO | Auditor independente e aceite do G5; merge; OAuth, dados pessoais, publicação, assinatura, nuvem e custo. |

**Branch:** `feat/jarvis-overnight-unified-2026-09-26` em worktree exclusiva. **HEAD de implementação:** `ace9b0b`; o commit documental final deve ser consultado com `git rev-parse HEAD`. `main` permaneceu em `8e7c09b`; G5 congelado em `4931c56`.

O G5 congelado **não passou** na autoauditoria nem na revisão estática de outro agente: sessão/grant revogados durante commit, versões de snapshot, ledger mutável, paginação e reconciliação de resposta perdida. O segundo revisor ainda identificou corrida alta herdada do G4 em mutações de Missões; foi corrigida em `2b79940` com regressões dinâmicas. As correções estão apenas nesta branch; revisão estática distinta **não equivale** a aceite formal. Consulte `G5_AUDIT.md`, `G5_SECOND_REVIEW.md` e `G5_OPEN_FINDINGS.md`.

O caminho demonstrável usa apenas dados fictícios: abra a API local pelo runner oficial, crie sessão e grants de Missões, crie uma Missão, selecione um arquivo fictício, confirme o envio, aprove o artefato e depois o conhecimento. O pacote de contexto mostra a origem; sem qualquer aprovação ele omite a fonte. `DEMO_GUIDE.md` contém o roteiro. O `.app` abre o shell offline e **não** usa essa API. O Android oferece apenas o shell web/código sincronizado; nenhum APK existe.

**Testes até o fechamento:** API 198/198; web 66/66, lint, typecheck e build PASS; fluxos E2E de arquivo e concessões manuais 2/2 cada; **duas rodadas completas consecutivas no código final `ace9b0b`: 54 PASS e 2 SKIP cada**, sem retries. Hashes em `CLIENT_BUILD_MATRIX.md`. Uma rodada intermediária 49/52 (2 skipped) falhou por expectativa antiga da navegação; foi corrigida, sem ocultação. O E2E oficial usa banco temporário e nenhum dado privado. O `.app` final abriu e seu processo foi encerrado após o smoke.

**Riscos prioritários:** G5 ainda sem segundo auditor; grants/sessões coordenados em um processo; SQLite local não protege contra operador com escrita total; importação pessoal real não autorizada; app nativo sem conexão com a API; Android sem toolchain. Não tratar o shell offline como assistente sincronizado.

**Três próximos passos:** (1) auditor independente no snapshot noturno e decisão explícita do proprietário sobre G5/merge; (2) SDK compartilhado e storage seguro antes de API em nativos/dados pessoais; (3) instalar JDK/SDK Android com licenças aceitas, gerar e testar APK debug em emulador autorizado.
