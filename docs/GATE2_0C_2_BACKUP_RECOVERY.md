# Gate 2.0-C.2 — Backup cifrado e restauração isolada

**Estado:** tecnicamente aceito para backup cifrado e restauração isolada exclusivamente com bancos sintéticos. A auditoria independente e seus limites estão registrados em [`docs/GATE2_0C_2_ACEITE.md`](GATE2_0C_2_ACEITE.md). A tag `gate2-c2-accepted-v0.1` aponta para o commit de implementação `c6f7ce5`.
**Limite autorizado:** backups e restaurações exclusivamente sintéticos e descartáveis. Esta entrega não autoriza uso do banco padrão, dados pessoais/institucionais, conectores ou dados reais.
**Pré-requisito:** Gate 2.0-C.1 aceito em `gate2-c1-accepted-v0.1`.

## Escopo

- A API HTTP não ganhou endpoints de backup/restauração. A operação é exposta somente por `apps/api/backup_cli.py` e pela biblioteca local usada pelo CLI/testes.
- O backup abre um banco existente em modo somente leitura e usa `sqlite3.Connection.backup()` para produzir um snapshot consistente enquanto SQLite pode estar em WAL. O comando não chama `initialize()` e não cria o banco de origem.
- A imagem é validada antes da cifragem: `integrity_check`, `foreign_key_check`, histórico/checksums das três migrações e comparação estrutural C.1.2.
- O formato `JARVISBK` v1 usa header JSON canônico autenticado como AAD, Argon2id (salt de 16 bytes; 64 MiB, 3 iterações, 4 lanes) para derivar chave de 32 bytes e AES-256-GCM com nonce aleatório de 12 bytes e tag de 16 bytes. O cabeçalho e o ciphertext são autenticados; parâmetros desconhecidos, cabeçalhos não canônicos e arquivos truncados são recusados.
- O banco e o arquivo de backup são limitados a 256 MiB. Arquivos e diretórios gerados usam permissões `0600` e `0700`; caminhos do repositório, symlinks, arquivos não regulares, pais compartilhados, colisões e substituições são recusados.
- O arquivo final é publicado sem substituição. A restauração autentica e descriptografa antes de criar seu destino, valida a imagem SQLite numa área temporária privada fora do repositório, grava e valida outra cópia em staging privado, e só então publica um `memory.sqlite3` em diretório novo `restore-v1-*`. A base padrão nunca é destino.
- Nenhuma fixture DEMO é consultada ou copiada. Banco, fontes, eventos, relações, proveniência e auditoria sintéticos são preservados como snapshot; sessões e grants não existem no esquema persistido e seguem voláteis.

O uso de `Connection.backup()` segue a API oficial do Python para cópia de banco SQLite aberto. A cifra autenticada segue AES-GCM; a derivação segue Argon2id da biblioteca `cryptography` ([SQLite backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup), [AES-GCM](https://cryptography.io/en/50.0.1/hazmat/primitives/aead/), [Argon2id](https://cryptography.io/en/50.0.1/hazmat/primitives/key-derivation-functions/)).

## Dependências e execução

`cryptography==50.0.1` foi fixada em `pyproject.toml` e `uv.lock` após `pip-audit` apontar vulnerabilidades conhecidas em 48.0.1. A versão travada inclui Argon2id. O fornecedor removeu os wheels x86_64 de macOS a partir da versão 49 e a documentação 50 lista macOS ARM64 entre as plataformas atualmente testadas; neste Mac Intel a instalação limpa Python 3.12 compilou 50.0.1 com Rust e OpenSSL 3.6.4. `uv.lock` fixa a distribuição e seus hashes, mas o compilador Rust e OpenSSL usados na compilação de fonte são pré-requisitos do host, não versões travadas pelo uv ([changelog 50.0.1](https://cryptography.io/en/50.0.1/changelog/), [plataformas e build macOS](https://cryptography.io/en/50.0.1/installation/)).

```bash
cd apps/api
uv python install 3.12
uv sync --locked --python 3.12
uv run --locked pytest -q
```

O CLI aceita apenas terminal interativo. A senha é lida com `getpass`, nunca por argumento, variável de ambiente ou arquivo de configuração; a criação pede confirmação.

```bash
cd apps/api
uv run --locked python backup_cli.py backup
uv run --locked python backup_cli.py restore jarvis-backup-v1-20260924T120000Z-a1b2c3d4.jvb
```

O backup usa o caminho padrão configurado em C.1 e grava em `backups/` ao lado do banco. O CLI de restauração aceita somente o nome de um arquivo dentro dessa pasta e grava em `restores/restore-v1-*/memory.sqlite3`. A restauração termina com caminho novo e isolado; mover ou ativar esse arquivo exige decisão e procedimento posteriores.

## Regressões versionadas

`apps/api/test_backup_recovery.py` usa exclusivamente `tmp_path` e conteúdo sintético. Cobre snapshot WAL/online, escritas concorrentes, integridade e igualdade de tabelas no round-trip, banco vazio, separação DEMO, senha incorreta, adulteração/truncamento, imagem e schema inválidos, colisões, caminhos e symlinks, permissões de sidecars, falhas de escrita/fsync, rollback, limites de senha, ausência de rotas HTTP, CLI sem argumento de senha e ausência de segredos em saída/logs.

## Riscos e limites residuais

- A senha perdida não pode ser recuperada. Exija uma frase longa e exclusiva; o CLI não persiste senha nem chave. Gestão segura de chaves/Keychain não faz parte deste incremento.
- Conteúdo claro existe temporariamente em memória e numa área temporária privada durante a validação/restauração. A remoção não promete apagamento físico seguro em SSD/APFS; FileVault, swap, processos do mesmo usuário e acesso físico continuam no limite de confiança do computador local.
- A cifra protege o arquivo de backup em repouso, mas não protege o banco ativo, o processo, a tela ou um usuário local já comprometido.
- Não há retenção automática, rotação/limpeza de backups, cópia para armazenamento externo, agendamento, recuperação para a base ativa ou política de exclusão. Esses itens dependem de decisão explícita do proprietário.
- Uma falha de hardware ou falta de espaço pode impedir publicação. A operação não sobrescreve arquivo existente e limpa staging quando possível; a integridade do backup deve ser verificada por restauração periódica.
- O limite de 256 MiB e os parâmetros Argon2id são fixos no formato v1. Mudá-los requer formato/versão compatível e testes de migração de backup.
- O banco SQLite ativo não possui criptografia própria. O limite de 256 MiB não representa o pico de memória: snapshot, arquivo cifrado e plaintext são materializados integralmente e podem coexistir como cópias durante a operação.
- A senha não pode ser recuperada se perdida. Não há armazenamento no Keychain nem política de rotação de chaves nesta etapa.
- A restauração usa plaintext temporário em área privada e tenta remover os artefatos ao final; isso não oferece apagamento físico garantido em SSD/APFS.
- C.2 não cria OAuth, Calendar real, Gmail, Drive, LLM, serviço de rede, acesso remoto, deploy, retenção de dados ou importação DEMO.

## Resultados desta implementação

Verificações reproduzidas pela implementação: instalação limpa `uv sync --locked --python 3.12` em ambiente/cache temporários — PASS, incluindo build de fonte de `cryptography==50.0.1`; smoke Argon2id/AES-GCM — PASS; `uv run --locked pytest -q` — **109 testes passaram**; `npm ci`; typecheck, lint, build e Vitest — PASS (**31 testes**); Playwright — **24 passaram** (desktop/mobile, build novo e servidor isolado); `npm audit` e `npm audit --omit=dev` — zero vulnerabilidades; `pip-audit` sobre export runtime de `uv.lock` após atualizar para 50.0.1 — zero vulnerabilidades. Pytest reporta avisos existentes de depreciação de `TestClient/httpx` e cookies. npm reportou avisos de depreciação do ESLint e do `next lint`; não são falhas. Os testes adversariais versionados estão em `test_backup_recovery.py`. A auditoria independente está registrada na seção seguinte e em `docs/GATE2_0C_2_ACEITE.md`.

## Auditoria independente e aceite

A auditoria independente reproduziu, em cópia temporária e sem abrir o banco padrão, `uv sync --locked --python 3.12` e **109 testes da API**; `npm ci`, **31 Vitest**, `npm audit`, `npm audit --omit=dev` e `pip-audit` também passaram. Probes independentes confirmaram snapshot de WAL com transações confirmadas, sobreposição real de gravações concorrentes com contagens consistentes de eventos/proveniência/auditoria, rejeição de adulterações criptográficas e restauração isolada validada. Uma falha `ENOSPC` foi simulada após escrita parcial; a origem permaneceu inalterada e não sobrou backup parcial.

Nesta auditoria, **build, lint, typecheck e Playwright não foram reproduzidos** porque nenhum arquivo frontend foi alterado; a implementação reportou essas verificações aprovadas, sem que isso conte como repetição independente. Consulte a matriz e o parecer completos em [`docs/GATE2_0C_2_ACEITE.md`](GATE2_0C_2_ACEITE.md). O aceite não amplia o limite sintético definido neste handoff.
