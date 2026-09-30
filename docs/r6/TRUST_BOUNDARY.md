# R6 — Fronteira de confiança do G5 local

## Escopo e TCB

G5 é local, sintético e monoprocesso. A Trusted Computing Base inclui:

- o processo e o código executável do JARVIS;
- o catálogo sintético versionado pelo servidor;
- os arquivos locais controlados normalmente pelo próprio processo;
- o SQLite quando operado pela aplicação.

Sessões e grants continuam voláteis. Um `domain_id` classifica o escopo, mas não concede acesso. A sessão e o grant local continuam sendo a autorização; a prova de proveniência de uma fonte não amplia essa autorização.

## Garantia suportada

**Toda adulteração inconsistente com a cadeia canônica existente deve falhar fechada.** A aplicação não deve apresentar como confiável conteúdo, hash, proveniência, `synthetic_verified`, seleção ou elegibilidade de contexto se não puder reconstruir uma única cadeia:

`principal → owner → mission → domain → artifact → selected source → catalog/version → fixture/bytes/hash → knowledge → review → snapshot → ledger, quando houver decisão`.

Referências cruzadas são reunidas sem filtrar primeiro pelo proprietário alegado. Isso permite detectar que uma relação aponta para a fonte, mesmo quando o `owner` ou o `source_id` alegado foi adulterado. A projeção só libera dados depois que todas as relações são verificadas contra o mesmo owner, missão, domínio, artefato, fonte, fixture, conhecimento e revisão. Snapshot e artefato corrente também precisam coincidir.

Uma revisão pendente sem decisão pode ser válida. Uma revisão decidida requer correspondência única e integral entre estado, ator, motivo, instante, revisão, versão, artefato, hash e snapshot no ledger. As decisões de conhecimento também precisam estar ligadas à origem aprovada e ao hash atual.

## Ameaças cobertas

G5 cobre clientes sem grant, payloads adulterados, claims importadas, stale state, replay, decisões de versões antigas, corrupção relacional detectável, mistura de owner/mission/domain/source, concorrência e revogação, e exposição de fonte cuja cadeia canônica não fecha.

## Limite de autenticidade

G5 **não** oferece autenticidade criptográfica contra:

- administrador do host ou processo com escrita irrestrita no SQLite;
- escritor que fabrique coerentemente revisão, snapshot, hashes, ledger, owner, missão, artefato e versão;
- administrador que altere código e banco ao mesmo tempo.

> Se a mesma autoridade pode escrever todos os dados e o suposto ledger de evidência, o banco não consegue provar qual pessoa realizou o evento. Hashes ou relações extras guardados no mesmo SQLite não resolvem isso.

Um probe documenta esse limite em `apps/api/test_r6_combined_tampering.py`. O probe passa ao demonstrar que uma fabricação integral e coerente está fora da garantia de autenticidade do G5. Isso não enfraquece os testes de divergência: uma inconsistência continua falhando fechada.

Autenticidade contra esse administrador exigirá uma raiz de confiança fora do SQLite em futuro gate de identidade/armazenamento seguro. R6 não adiciona assinatura, HMAC, Keychain, Secure Enclave, Keystore, PKI, chave externa ou serviço remoto.

## Fora do escopo

API pública/remota, OAuth, fontes reais, dados pessoais, Gmail, Drive, Calendar real, LLM, MCP, voz, sincronização, multiworker, deploy, serviços persistentes e G6 continuam proibidos. A interface API escuta somente em loopback. R6 não declara G5 formalmente aceito.

Para a matriz resumida de ameaça/controle, ver [ADR-010](../adr/010-local-review-trust-boundary.md). Para cada claim persistido e projeção, ver [matriz de estado confiável](TRUSTED_STATE_MATRIX.md).
