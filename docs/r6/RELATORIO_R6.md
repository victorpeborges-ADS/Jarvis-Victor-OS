# Relatório técnico — candidata JARVIS R6

## Baseline e objetivo

- Branch: `feat/jarvis-unified-r6-2026-09-30`.
- Baseline: R5 `7306093cde4bdfa15b3adfead5e48f1e4d497dad`.
- Main informada: `8e7c09bb303deb6fe444a3a455961519a5f414d2`.
- Objetivo: fechar a exposição P1 causada pela quebra simultânea de relações; declarar corretamente o limite contra administrador do mesmo SQLite; adicionar probes combinatórios; humanizar o timezone.
- Resultado de integração: nenhuma alteração foi integrada à main.

## IMPLEMENTADO

- Criada `resolve_trusted_source_projection`, projeção canônica comum a Missões, fontes selecionadas, revisões e knowledge/contexto.
- Descoberta de fonte deliberadamente não filtra por owner. A fonte ainda é localizada por relações/artefato/snapshot/knowledge/review mesmo quando um campo da cadeia foi adulterado; a prova final exige uma única identidade coerente.
- Validada a igualdade entre a referência selecionada do artefato, snapshot, bytes, fixture/catalog, owner, missão, domínio, conhecimento e revisão. Revisão decidida também requer o estado canônico do ledger.
- Missão e revisão agora omitem bytes, hashes, provenance, seleção/classificação e referências quando a cadeia não fecha; metadados são substituídos por placeholder.
- Knowledge procura relações pela própria ID, revisão ligada, decisão e hash/mission para não confiar apenas em `kind=selected_original`. Uma claim trocada para `skill_derived` com links desligados continua em quarentena.
- Criados 19 probes combinatórios cobrindo as 18 classes solicitadas, mais a alteração combinada de tipo e links de knowledge. O conjunto verifica lista de fontes, missão, review, knowledge, decisão, contexto, skill `build-context` e conclusão da missão.
- Adicionado teste de fronteira aprovado que demonstra, sem mascarar, que um escritor SQLite capaz de fabricar todo o conjunto coerente está fora da garantia de autenticidade G5.
- ADR-010 e os seis documentos `docs/r6/` registram cadeia canônica, threat model, matriz de estado, probes, resultados e handoff. Sem migração nova.
- UI Agora exibe `Demonstração · São Paulo` e `Horário de Brasília`; timezone técnico interno permanece inalterado. Teste de copy impede `America/Sao_Paulo` no texto visível.

## PROVADO

- As 19 adulterações inconsistentes falham fechadas através das superfícies documentadas; o teste separado do administrador coerente passa como demonstração explícita de limite.
- API integral: 285 testes aprovados. Vitest: 66 aprovados. Typecheck, lint e build passaram. Duas rodadas E2E sem retries: cada uma com 64 aprovações e 2 skips intencionais específicos por projeto.
- Inspeção visual/responsiva automatizada nas larguras 320, 360, 390, 600, 767, 768, 769, 820, 1024 e 1440 px; capturas representativas de 320, 390, 767, 768, 769, 1024 e 1440 px.
- As corridas de leitura/reconciliação mantêm as duas ordens existentes, sem deadlock. As migrações 0013–0015, revalidação, rollback/retry, restart e integridade seguem verdes na API integral.

## ASSUMIDO/TCB

- Processo e código JARVIS, catálogo/versionamento sintético, arquivos locais controlados pelo processo e SQLite operado normalmente pela aplicação formam o TCB do G5.
- Autorização permanece em sessão/grants locais voláteis; o domínio não concede acesso. A aplicação continua monoprocesso e loopback-only.
- Dentro desse TCB, stored claims não são prova: projeções reconstroem as relações e falham fechadas em divergências detectáveis.

## FORA DO ESCOPO

- Autenticidade criptográfica contra administrador do host ou escritor que fabrique coerentemente código/banco, inclusive revisão + snapshot + hashes + ledger + owner + missão + artefato + versão.
- OAuth, serviços externos, contas reais, PII, Gmail, Drive, Calendar real, API pública/remota, multiworker, sincronização, MCP, LLM, voz, deploy, assinatura/HMAC, Keychain/Keystore e G6.
- G5 não recebeu aceite formal nesta sprint.

## UX e capturas

- [Mobile — 320 px](captures/R6_mobile_320px.png)
- [Mobile — 390 px](captures/R6_mobile_390px.png)
- [Mobile — 767 px](captures/R6_mobile_767px.png)
- [Desktop — 768 px](captures/R6_desktop_768px.png)
- [Desktop — 769 px](captures/R6_desktop_769px.png)
- [Desktop — 1024 px](captures/R6_desktop_1024px.png)
- [Desktop — 1440 px](captures/R6_desktop_1440px.png)

## Execução e higiene

O preflight, stdout/exit do diagnóstico, Git/SHA/ancestralidade, worktrees, hashes dos quatro arquivos não rastreados, `git diff --check`, `git fsck --full` e portas estão registrados no handoff final desta task. API/web locais foram encerrados pelos runners; nenhuma integração à main, push, tag, deploy ou instalação persistente foi realizada.

Detalhes e limitações constam em [fronteira G5](TRUST_BOUNDARY.md), [matriz de claims](TRUSTED_STATE_MATRIX.md), [probes combinatórios](COMBINED_TAMPERING_TESTS.md) e [matriz de testes](TEST_MATRIX.md).
