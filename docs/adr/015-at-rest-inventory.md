# ADR-015 — Inventário de proteção em repouso

- Status: inventário. Não escolhe algoritmo e não migra banco real.
- Date: 2026-10-21.
- Supersedes: none.

A escolha de cifra continua no ADR-013, sem algoritmo adotado. Este documento só nomeia onde o dado sintético da candidata mora.

| Superfície | Onde está | Destinatário |
|---|---|---|
| Tabelas | SQLite do `SQLiteMemoryStore`, fora do repositório | `owner`, domínios `dom_synthetic_*` |
| WAL e SHM | Ao lado do arquivo aberto enquanto o modo WAL está ligado | O mesmo processo que abriu o banco |
| Índices | Índices declarados nas migrations, sem índice de texto separado | As leituras do próprio banco |
| Anexos | `synthetic_artifacts.body` e documentos publicados pelo registro de skills | O domínio gravado na linha |
| Logs | Access log do runner desligado; falhas sem corpo de captura | Operador local, sem destino remoto |
| Caches | Sessão, grant e texto visível do gateway, só na memória do processo | O processo atual |
| Backups | `.jvb` cifrado na pasta irmã `backups/` | Quem tem a senha do ensaio |
| Chaves | Senha de backup só no momento do comando; segredo UDS na memória da sessão; nenhuma chave de cifra do SQLite ativo | Não há destinatário de chave de conteúdo |
| Pasta aprovada | Texto extraído em `approved_files`, caminho relativo, sem symlink | O domínio do job |

Um backup anterior ainda pode repor texto apagado no banco aberto. Isso não é decidido de novo aqui.
