# Gate 2.0-C.1 — Memória local

**Estado:** implementação na branch `feat/gate2.0-c1-memoria`, aguardando auditoria independente.
**Base:** `main` @ `b45fbb43` (`gate2-b-accepted-v0.1`).
**Limite:** memória local vazia e testes com conteúdo exclusivamente sintético. Sem conexão de fontes externas.

## Decisões implementadas

- O repositório `SQLiteMemoryStore` fica atrás da API; a interface não abre nem consulta o arquivo SQLite.
- O banco padrão fica fora do repositório: `~/Library/Application Support/JARVIS/memory.sqlite3` no macOS; nos demais sistemas, `$XDG_DATA_HOME/JARVIS/memory.sqlite3` (ou `~/.local/share/JARVIS/memory.sqlite3`). `JARVIS_DATABASE_PATH` permite escolher outro arquivo, também fora do repositório.
- O diretório do banco precisa pertencer ao usuário atual e ser privado; diretórios novos usam modo `0700`, banco `0600`. Caminhos dentro do repositório, symlinks, arquivos não regulares e diretórios existentes com permissões compartilhadas são recusados. O processo falha fechado se não puder preparar/abrir/verificar o banco.
- SQLite usa WAL, `synchronous=FULL`, foreign keys, `busy_timeout`, transações `BEGIN IMMEDIATE` e migrações SQL versionadas com SHA-256. DDL e registro de versão da migração são transacionais.
- `memory_models.py` valida entidades imutáveis e estritas para fonte, evento, proveniência, entidade, relação e escopo mínimo de leitura. `GrantIn`/`Grant` da API continuam tipados e voláteis; sessão e concessão não foram adicionadas ao banco.
- Cada evento guarda referência da fonte, instante observado, última verificação, validade, confiança, método/instante de classificação, sensibilidade e `domain_id`. Domínio ausente é não classificado e não é retornado. IDs de domínio aceitos nesta etapa são identificadores exclusivamente sintéticos (`dom_synthetic_a` a `_h`), sem mapeamento para domínios institucionais ou pessoais.
- Listagem, recuperação por ID e briefing exigem sessão válida e concessão ativa em memória. A API transforma a concessão em escopos canônicos (principal, conector, recurso e domínios); o repositório revalida os escopos e aplica-os na consulta SQL, junto com `dataset='real'`. `domain_id` é classificação, não autorização. Revogar ou perder a concessão remove o acesso imediatamente, mesmo com o evento persistido.
- `audit_entries` registra apenas operação allow-listed, resultado, quantidade, dataset e instante. Não armazena principal, IDs de registro, títulos, payload, sessão ou concessão. A retenção dessa tabela ainda depende de decisão do proprietário; eventos de login negado e operações de concessão volátil não são persistidos nesta etapa.
- Uma origem e um evento não são criados pelo frontend. Gravações do repositório são interfaces de serviço internas, sem rota pública de escrita nesta etapa.
- Não existe rotina de migração/importação de `fixtures/demo.json`; as tabelas do arquivo real são criadas vazias. As fixtures e endpoints DEMO continuam separados.

## Modelo persistido

A migração `apps/api/migrations/0001_initial.sql` cria `sources`, `events`, `event_provenance`, `entities`, `relations`, `relation_evidence` e `audit_entries`, com chaves estrangeiras, restrições e índices. Não cria tabelas de sessão, concessão, token ou cursor de sincronização. A auditoria é operacional e minimizada, não uma cópia de conteúdo. A migração confere checksum em inicializações futuras; uma mudança incompatível exige nova migração versionada.

Falha de migração é revertida sem registrar versão parcial. `quick_check` e `foreign_key_check` são executados na inicialização. Falha/corrupção impede servir a aplicação; falhas durante consultas retornam erro genérico sem caminho, conteúdo ou payload. Linhas malformadas são omitidas e registradas em log sem dados do evento.

## Dados e execução

O banco padrão é criado vazio quando o runner suportado inicia a API. Nesta entrega, **não inicializei esse arquivo padrão**. Testes criam bases sintéticas em `tmp_path` e em diretórios temporários; não leem ou semeiam dados pessoais/institucionais e não copiam as fixtures DEMO. O `dataset='real'` é a separação de armazenamento futuro, não uma afirmação de que os exemplos de teste sejam dados reais.

```bash
cd apps/api
uv sync --locked --python 3.12
JARVIS_LOCAL_PASSPHRASE='defina-uma-frase-local' uv run --locked python serve.py
```

O runner oficial continua limitado a loopback conforme Gate 2.0-B. Não execute Uvicorn diretamente. A UI Gate 1 ainda não consome a API real; ela segue em modo DEMO.

## Verificações desta entrega

- API: `uv sync --locked --python 3.12`; `uv run --locked pytest -q` — **68 passaram**.
- Frontend: `npm run build`, `npm run typecheck`, `npm run lint` e `npm test -- --run` — **31 testes Vitest passaram**.
- E2E: `npx playwright test --reporter=line --workers=2` — **24 passaram**, projetos desktop e mobile, build novo e servidor isolado.
- Dependências: `npm audit` e `npm audit --omit=dev` sem vulnerabilidades; `pip-audit` sobre dependências runtime exportadas de `uv.lock`, sem vulnerabilidades conhecidas.

Lint não apontou problemas. Pytest emitiu dois avisos de depreciação de TestClient/httpx e cookies por requisição; não são falhas de teste.

Os testes incluem banco vazio e migração repetida, rollback de migração e transação, reinício de processo, idempotência de evento, validação de entrada e linha persistida, restrições relacionais, isolamento dos oito domínios sintéticos, listagem/ID/briefing sem concessão, revogação após persistência, ausência de importação DEMO e ausência de persistência de sessão/grant.

## Riscos e pendências

- SQLite não está cifrado pela aplicação. A proteção atual depende de conta local e permissões do sistema de arquivos; FileVault e política de backup do sistema são externas a este incremento.
- Ainda não existe backup/restauração operacional, política aprovada de retenção/exclusão, auditoria de eventos de autenticação/concessão, sincronização nem adaptador Calendar.
- Sessões e concessões são voláteis por decisão de segurança durante esta transição: reiniciar exige novo login e nova concessão. Persistência e ciclo de vida dos grants aguardam decisão explícita.
- O passphrase permanece configurado localmente pelo mecanismo existente. HTTP local não oferece as propriedades de transporte de HTTPS contra processos locais comprometidos.
- Os identificadores de domínio nesta fundação são somente sintéticos. O mapeamento e a autorização para qualquer domínio/dado real continuam bloqueados até revisão e aceite próprios.
- Nenhum resultado desta etapa autoriza OAuth, dados reais, Google Calendar, Gmail, Drive, LLM, backup cifrado, acesso remoto ou deploy.
