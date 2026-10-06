# MAC-002.1 — Política de cleanup seguro

## Regras

| Situação | Ação |
|---|---|
| Socket foi criado na sessão e o FD original segue disponível | Remover `runtime.sock` com `unlinkat` relativo ao FD do diretório daquela geração. |
| Child sai, inclusive por EOF ou falha de bind | `Drop` do config tenta remover somente a folha fixa relativa ao diretório validado; segredo é zerado best-effort. |
| Parent revoga por STOP, EOF observado pelo processo ou crash/reap | Desativa capability e remove o socket pelo FD retido; `cleanup_done` torna chamadas repetidas idempotentes. |
| Nome da sessão foi renomeado, substituído por symlink ou identidade não confere | Não operar pelo nome mutável. O handle original continua ancorando unlink do socket; qualquer path substituto/target externo é preservado. |
| Não é possível provar ownership/identidade | Falhar fechado, registrar categoria segura sem path/segredo e preservar artefato. A próxima geração recebe nome aleatório novo. |

## Diretório vazio

O runtime deixa `.jv-*` vazio após remover `runtime.sock`. Não executa `remove_dir` nem `remove_dir_all` sobre o nome mutável da sessão. Esse resíduo pequeno é intencional e limitado a um diretório por geração. O nome aleatório reduz colisões; não é tratado como controle de acesso.

O `Drop` de `TransportSession` em build de teste pode remover o diretório de teste quando `symlink_metadata` ainda comprova o mesmo `dev`/`inode` e o socket já não existe. Essa conveniência é `cfg(test)` e não participa do runtime distribuído. Testes adversariais limpam explicitamente somente os alvos que criaram.

## Inventário de mutações

- Produção: `unlinkat` relativo ao FD da sessão para `runtime.sock` em `TransportSession::cleanup_endpoint` e `ChildTransportConfig::drop`.
- Produção: `create_dir` e `set_permissions` no caminho recém-gerado durante setup; em falha, o código preserva o diretório e não tenta remoção por pathname.
- `remove_file`/`remove_dir` adicionais em `transport.rs` estão sob `#[cfg(test)]` e limpam canários, substituições e diretórios de teste conhecidos.
- Não há `remove_dir_all` no lifecycle de produção.

Logs de cleanup informam apenas resultado/categoria. Não incluem path, nonce, capability ou corpo HTTP.
