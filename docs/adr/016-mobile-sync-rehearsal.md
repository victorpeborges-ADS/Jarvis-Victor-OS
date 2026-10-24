# ADR-016 — Ensaio móvel sem APK e sem sync de rede

- Status: aceite escrito da frente 10, só no processo. APK, aparelho e emulador continuam NOT TESTED.
- Date: 2026-10-22.
- Supersedes: none.

## Decisão

O processamento deste ensaio fica no processo que abre o SQLite temporário. As opções A–E de `docs/g6/ANDROID_ARCHITECTURE.md` não viram serviço. O transporte declarado é `in_process`. O armazenamento de relay declarado é `ausente`. Outro transporte é recusado.

Captura sintética offline leva o rótulo "somente neste aparelho" e não afirma que o Mac executou. Execução que depende do Mac continua exigindo o Mac; com o Mac indisponível o estado é `indisponivel` e `promised` fica falso. Este ensaio não executa trabalho no Mac nos dois casos.

O custo permanece `não medido`.

## Identidade

`app.jarvis.mobile`, `demo` e qualquer identificador com prefixo `demo-` ou `demo_` não são identidade. A identidade do ensaio é um par Ed25519 gerado na memória. O arquivo guarda a chave pública e a impressão. A chave privada não entra no arquivo. TTL de 3600 segundos, rotação, perda e revogação tiram o direito de aplicar operação.

## Exclusão

A exclusão usa a política da frente 1. A linha sai do banco aberto. `historical_backup_may_keep_text` continua verdadeiro. O arquivo `.jvb` já gravado não é reescrito. Uma operação posterior, mesmo com revisão maior e relógio adiantado, não regrava o item no ensaio nem no banco aberto. Isso não escolhe tombstone, expiração nem recusa de restore para backups antigos: o ADR-012 segue sem essa decisão.

Conflito de mesma revisão não troca o corpo em silêncio. Revisão mais antiga não vence pelo relógio. O mesmo `op_id` não duplica. Domínio fora de `dom_synthetic_a` é recusado.

## Fora deste ensaio

APK, aparelho, emulador, `localStorage` como memória do produto, canal remoto, OAuth e conta real. Mensagem encaminhada, contato e voz não autorizam efeito. O envio remoto permanece BLOCKED.

## Próximo gate

Aparelho ou emulador autorizado, antes de qualquer APK. Até lá, DEVICE_TEST e APK_BUILD ficam NOT TESTED.
