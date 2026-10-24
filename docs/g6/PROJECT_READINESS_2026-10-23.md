# Aceite e pendências — 23/10/2026

Este relatório concilia documentos. Não executa testes, não abre janela e não aceita uso nem distribuição.

Candidata: `codex/jarvis-integration-candidate`, HEAD `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`, worktree suja e sem stage. Plano: `feat/gate2.0-e-integracao-web-api`, HEAD `e648e92467396ce67b75019858fbcd0ee5557042`. A seção 14 do roadmap compartilhado continua sendo o retrato de 18/10 e 21/10. Onde ela diverge dos handoffs posteriores, a data mais nova prevalece e a frase antiga permanece no roadmap.

## Evidência citada, por data

| Data | O que foi registrado | O que não é |
|---|---|---|
| 22/10, suíte API após cifra | 735 passed, depois 736 passed, 2 warnings | Não é a suíte atual |
| 22/10, Web offline | 68 passed em 16 arquivos; typecheck e build PASS. Antes: 67 passed, 1 failed por `listen EPERM` | Build e Vitest não são smoke visual |
| 22/10, Rust sem filtro de Keychain | 112 unitários, 1 integração, 9 ignored | Não é a invocação de 23/10 |
| 22/10, Keychain de arquivo | 6 passed no grupo focado, harness temporário | Não cobre login, prompt nem Data Protection Keychain |
| 22/10, IPC | 26 passed | Superado em contagem pela rodada de 23/10 |
| 23/10, API após a conversa | **840 passed, 2 warnings**, exit 0 | A rodada anterior do mesmo dia, 838 passed, não é esta |
| 23/10, Rust desta validação | lib **108 passed**, integração **1 passed**, **9 ignored**, **6 filtrados** pelo `--skip keychain` | Os 6 filtrados não são PASS de Keychain |
| 23/10, Keychain descartável, execução separada | **6 passed, 0 failed** | Login, prompts reais e Data Protection Keychain: **NOT TESTED** |
| 23/10, IPC, typecheck e build do frontend desktop | **28 passed**; `tsc --noEmit` PASS; Vite em `/tmp` PASS | Não abre janela e não substitui smoke |
| 23/10, banco selado focado | Python 13 passed; sem mudança de produção | Não é a suíte de 840 e não cifra o banco diário |
| 23/10, ciclo da rotação | `test_storage_key_rotation.py` **34 passed**. Suíte API **891 passed, 2 warnings**, 436,02 s. Lib Rust **122 passed, 9 ignored**. UDS de rotação **1 passed**, `cleanup_removed=true`. IPC **28 passed**. `tsc --noEmit` PASS. `cargo fmt --check` PASS. Build `--no-bundle` SHA-256 `19a5e53ed8829e36590628004506c912e03a4d2f0c70958af3d9984abd14016f`; binário não aberto | Não é smoke. Login Keychain e Data Protection Keychain: NOT TESTED. O banco diário não foi inspecionado |

Smoke visual permanece **BLOCKED/NOT TESTED** em todas essas rodadas. Mobile permanece **BLOCKED** por dependências ausentes no cache offline. Provider real, OAuth, efeitos externos, APK e assinatura ficam fora. O banco diário não foi migrado nem validado como cifrado. A verificação de segredos está **BLOCKED**: não há scanner local adequado e nenhuma varredura improvisada foi feita. A possível credencial mencionada antes está **não confirmada** e não foi usada. A rotação demonstrada é só a da chave de um banco sintético temporário.

## Matriz por frente

| Frente | Implementado | Validação automática | Smoke visual | Dependência ou autorização | Próximo gate |
|---|---|---|---|---|---|
| 1. Memória, captura, exportação e exclusão | Categorias, captura, proveniência e purga do banco aberto. Exportação local pelo seletor nativo está no handoff de 22/10. A seção 14 ainda diz que o comando de exportação está ausente; essa frase é anterior. Tombstone da exclusão aberta e replay no restore cifrado estão no handoff de 22/10. A seção 14 ainda diz que tombstone não foi implementado. Expiração de tombstone continua sem decisão. Cópias históricas não são sanitizadas. | Inclusa na API de 840. Grupos focados anteriores não substituem essa suíte. | NOT TESTED | Banco diário fora. Backup legado ainda exige confirmação de ressurgimento. | Não tratar exclusão aberta como apagamento de backup antigo. |
| 2. Conversa, DEC-14, fato confirmado e artefato | Pergunta da interface até `POST /v1/app/conversation/ask`. DEC-14 persiste só ID opaco e metadados; prompt, resposta, fontes, tokens e grants não persistem. Reabrir o ID não restaura sessão. Fonte `confirmed_fact` citável. Artefato com origem, versão e hash; corpo maior por fragmento, teto de 2.048 bytes. A frase de 21/10 de que loop e artefato não estão no IPC foi superada. | API 840. IPC 28, incluindo a ponte simulada de `confirmed_fact`. Rust desta validação aceitou o tipo e recusou `tool` e outro domínio. Focados de conversa (59) não são a suíte inteira. | NOT TESTED | Provider real BLOCKED. Custo desconhecido continua `unmeasured`. | Não promover o provider falso a avaliação de modelo. |
| 3. Provider real | Corpus de 60 casos e relatório `blocked`, sem egress, em 21/10. | A tarifa local de teste não é chamada remota. Suítes posteriores do falso não autorizam o real. | NOT TESTED | Destino, modelo, teto de gasto e autorização ausentes. | Permanece BLOCKED. |
| 4. Skill e ingestão | TXT/Markdown na pasta aprovada. Script em quarentena. PDF simples com página na origem. DOCX, XLSX e PPTX recusados. FTS não adotada. | Aceite escrito de 21/10, depois coberto pela API de 840. Não reexecutado isoladamente em 23/10. | NOT TESTED | OCR e imagem fora. | Não executar manifesto em quarentena. |
| 5. Banco selado sintético e Keychain | Snapshot `JVSDB`, SQLite em memória, chave pelo comando `runtime_storage_unlock` e UDS. Processo nasce bloqueado. Sem fallback para SQLite claro. Banco diário inerte e não inspecionado nesta rodada. Rotação sintética: journal AES-GCM sem bytes de chave, item novo distinto e conta antiga removida só depois do commit. Um persist posterior pode mudar o nonce; a chave que abre o envelope continua válida e o digest do journal segue como âncora de crash. Perda de chave não gera substituta. | Rotação focada **34 passed**. Suíte API **891 passed, 2 warnings**. Lib Rust **122 passed, 9 ignored**, incluindo o UDS descartável com `cleanup_removed=true`. IPC **28 passed** e typecheck PASS. Commit encerra o rollback; a cópia só sai depois da geração nova validada e da conta antiga ausente. | NOT TESTED | Login Keychain, prompt real e Data Protection Keychain: NOT TESTED. | Não remover o perfil temporário nem cifrar o banco diário sem decisão nova. |
| 6. Conectores em fixture | Cinco conectores falsos. Schema ausente bloqueia. Revogação tira o cache. Sem rede. | Aceite de 21/10, coberto depois pela API de 840. Sem reexecução isolada em 23/10. | NOT TESTED | OAuth e contas reais BLOCKED. Dia inteiro sem contrato. | Não tratar fixture como conta conectada. |
| 7. Aprovação, outbox e automação | Serviço falso, dry-run, retry sem duplicar, cancelamento que não desfaz efeito já confirmado. Aviso local com horário silencioso. | Aceite de 21/10, coberto depois pela API de 840. | BLOCKED. A UI não exibe a outbox, segundo o handoff. | Efeito externo BLOCKED. | Não marcar cancelado um efeito já confirmado. |
| 8. Instalação e assinatura | Ensaio temporário que recusa worktree e banco diário. Sem certificado, assinatura devolve BLOCKED. | Aceite de ensaio em 21/10. Builds `--no-bundle` de 22/10 existem e não foram executados. | BLOCKED. Build não é smoke. | Certificado e notarização ausentes. | Instalação limpa e pacote verificável continuam abertos. |
| 9. Voz e tela | Contrato de estado em 22/10: gesto, foco, cancelamento e transcrição que não envia. Wake word desligada. Tela real BLOCKED. A seção 14 ainda diz que não há fluxo de voz; o handoff de 22/10 é mais novo e limita o aceite ao contrato. | Suítes da época e, depois, a API de 840. IPC de 23/10 confirma o aviso de voz desativada na árvore, não um leitor de tela real. | NOT TESTED. Microfone não aberto. | Áudio real, observação real e ação nativa BLOCKED. | Não tratar o contrato como teste acústico. |
| 10. Android | Ensaio no processo: identificador de demonstração não é identidade; sync não regrava item apagado no banco aberto. A seção 14 ainda diz que sync não existe; o handoff de 22/10 é mais novo e não produz APK. | Aceite de ensaio em 22/10, depois coberto pela API de 840. | NOT TESTED | Mobile BLOCKED por dependências ausentes. APK, aparelho e emulador NOT TESTED. | Não prometer execução com o Mac desligado. |

## Gates abertos

- Visual: smoke da janela, leitor de tela real, seletor nativo observado e outbox na interface.
- Confiança do dado: banco diário, expiração de tombstone, sanitização de cópia histórica e rotação de chave perdida.
- Identidade local: Keychain de login, prompt real e Data Protection Keychain.
- Externo: provider real, OAuth, contas, efeito externo, assinatura e notarização.
- Distribuição: instalação limpa, APK e dependências mobile.
- Higiene: scanner de segredos e a credencial não confirmada.

## O que esta consolidação não faz

Nesta rodada a suíte API foi **891 passed, 2 warnings**. IPC **28 passed** e `tsc --noEmit` PASS. O build `--no-bundle` não é smoke. Não declara rotação de credencial. Não aceita uso nem distribuição.
