# JARVIS — Aceite independente do Gate 2.0-C.2

## Decisão e escopo

**Resultado: aceito tecnicamente apenas para backup cifrado e restauração isolada de bancos sintéticos descartáveis.** A auditoria não autoriza abrir, inicializar, restaurar ou substituir o banco padrão, nem usar dados pessoais/institucionais, OAuth, conectores reais, deploy ou acesso remoto.

- Branch auditada: `feat/gate2.0-c2-backup-recovery`
- Commit de implementação: `c6f7ce5d3175bc4cc24228d0cfbed28f5cec19c8`
- Commits do incremento: `74a8510` e `c6f7ce5`
- Baseline: `main` em `3a31053`
- Tag do C.1 preservada: `gate2-c1-accepted-v0.1` → `2609bdb9ea511c83b45b464d9d1214638f452196`
- Tag deste aceite: `gate2-c2-accepted-v0.1` → `c6f7ce5d3175bc4cc24228d0cfbed28f5cec19c8`

O repositório original permaneceu limpo durante a auditoria. Instalações e ensaios foram feitos numa cópia temporária com bancos sintéticos. O banco padrão não foi aberto nem inicializado.

## Matriz de verificações

| Área | Resultado | Evidência independente |
|---|---|---|
| Snapshot SQLite/WAL | **PASS** | Snapshot feito por `Connection.backup()` em conexão de origem somente leitura. Uma origem com WAL de 3.378.432 bytes e gravações confirmadas foi copiada; o hash do arquivo principal permaneceu estável. |
| Escritas concorrentes | **PASS** | Probe coordenado forçou gravações enquanto a cópia por páginas estava ativa. O banco restaurado tinha contagens iguais de eventos, proveniência e auditorias de evento; não houve registros parciais. |
| Banco ocupado | **PASS** | Uma transação WAL não confirmada ficou aberta durante o backup. A cópia isolada não incluiu a transação pendente. |
| Criptografia e formato | **PASS** | Versão, parâmetros de KDF e tamanhos de salt/nonce incompatíveis foram rejeitados; duas criações geraram salt e nonce distintos. A adulteração de SQLite autenticado também foi rejeitada. |
| Falhas de escrita | **PASS** | Simulação de `ENOSPC` após escrita parcial preservou o hash da origem e não deixou arquivo parcial. Erros de escrita e `fsync` também são cobertos pelos testes versionados. |
| Restauração | **PASS** | `integrity_check`, `foreign_key_check`, migrações e estrutura foram validados; a imagem restaurada preservou tabelas e relações. SQLite estruturalmente inválido não publicou destino. |
| Caminhos, permissões e colisões | **PASS** | A suíte versionada cobre symlinks, arquivos e diretórios privados, colisões, traversal, falhas após publicação e limpeza de staging. Arquivos preexistentes não são sobrescritos. |
| Separação de dados e superfície HTTP | **PASS** | Nenhuma rota HTTP foi adicionada. Testes confirmam que fixtures DEMO, sessões e grants não entram no banco de backup. |
| Dependências | **PASS** | Instalação Python 3.12.14 x86_64 com lock; `cryptography==50.0.1`, Argon2id e OpenSSL 3.6.4. `pip-audit` do ambiente instalado e do runtime travado não encontrou vulnerabilidades. `npm audit` e `npm audit --omit=dev` encontraram zero vulnerabilidades. |
| Frontend | **PASS no escopo não afetado** | `npm ci` e Vitest: 31 testes passaram. Nenhum arquivo frontend foi alterado. Build, lint, typecheck e Playwright foram reportados como aprovados pela implementação, mas não foram repetidos nesta auditoria. |

### Reexecução de testes

- `uv sync --locked --python 3.12`: **PASS**, Python 3.12.14, Mac Intel (`x86_64`).
- `pytest -q`: **109 passed**, dois avisos de depreciação relacionados ao TestClient/httpx e cookies.
- Probes independentes: WAL confirmado; sobreposição de escritor durante backup; transação não confirmada excluída; salt/nonce distintos; alterações de cabeçalho rejeitadas; SQLite autenticado mas estruturalmente inválido rejeitado; simulação de `ENOSPC` sem alteração da origem.
- `npm ci`: **PASS**, com avisos de scripts de instalação não aprovados e pacotes depreciados.
- Vitest: **31 passed** em seis arquivos.
- `npm audit` e `npm audit --omit=dev`: **0 vulnerabilidades**.
- `pip-audit --strict` no ambiente instalado e auditoria do export runtime travado: **nenhuma vulnerabilidade conhecida**.
- Build, lint, typecheck e Playwright: **não repetidos** pela auditoria independente, pois o diff não continha alterações frontend; a implementação reportou PASS (incluindo 24 testes Playwright desktop/mobile).

A coleta inicial do pytest foi interrompida porque o override de salvaguarda do banco ficou dentro da raiz do repositório temporário e foi corretamente recusado. O override foi movido para um diretório irmão, fora dessa raiz, e a execução completa passou. Nenhum banco foi criado na tentativa inicial.

## Evidências no código e testes

- Snapshot online, formato e limites: [`backup_recovery.py`](../apps/api/backup_recovery.py#L31), [`backup_recovery.py`](../apps/api/backup_recovery.py#L234), [`backup_recovery.py`](../apps/api/backup_recovery.py#L380).
- Publicação sem substituição e `fsync`: [`backup_recovery.py`](../apps/api/backup_recovery.py#L451), [`backup_recovery.py`](../apps/api/backup_recovery.py#L619).
- Senha somente no terminal interativo: [`backup_cli.py`](../apps/api/backup_cli.py#L42).
- WAL, concorrência, round-trip e ausência de sessões/grants: [`test_backup_recovery.py`](../apps/api/test_backup_recovery.py#L87), [`test_backup_recovery.py`](../apps/api/test_backup_recovery.py#L156).
- Adulteração, SQLite inválido, colisões, permissões e falhas de escrita: [`test_backup_recovery.py`](../apps/api/test_backup_recovery.py#L186), [`test_backup_recovery.py`](../apps/api/test_backup_recovery.py#L246), [`test_backup_recovery.py`](../apps/api/test_backup_recovery.py#L267), [`test_backup_recovery.py`](../apps/api/test_backup_recovery.py#L338).

## Riscos residuais e limites

- **Banco ativo:** o arquivo SQLite ativo não tem criptografia própria; a cifra cobre apenas o arquivo de backup.
- **Tamanho e memória:** banco/arquivo limitados a 256 MiB, mas snapshot, ciphertext e plaintext são materializados integralmente; o pico de RAM pode ser várias vezes o limite. Não houve benchmark próximo ao teto.
- **Senha:** perdida, não pode ser recuperada. Não existe Keychain nem rotação de chaves.
- **Plaintext temporário:** a validação/restauração cria arquivos claros em diretórios privados e tenta removê-los. Não há garantia de apagamento físico em SSD/APFS.
- **Ciclo de vida:** não há retenção automática, limpeza/rotação de backups ou restauração sobre a base ativa.
- **Falhas físicas:** `ENOSPC`, escrita e `fsync` foram simulados; não foi induzida falta física de espaço ou perda de energia.
- **Toolchain Intel:** a instalação bloqueada foi bem-sucedida neste Mac Intel; Rust/OpenSSL usados para compilar são dependências de build do host, fora do lock de runtime.

Qualquer uso com dados pessoais exige revisão e autorização específicas para proteção da base ativa, gestão da senha/chaves, política de retenção, recuperação, tamanho/memória e tratamento dos arquivos temporários. Este aceite não inicia o próximo gate nem autoriza integração real.
