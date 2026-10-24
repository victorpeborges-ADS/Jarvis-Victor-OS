# Registro local de skills e documento sintético

Worktree `/Users/vic/.codex/worktrees/jarvis-integration-candidate/Jarvis-Victor-OS`, branch `codex/jarvis-integration-candidate`. Registro e schemas em `apps/api/skill_registry.py`; teste focado inicial: `uv run --locked pytest -q test_skill_registry.py` — 15 passed. A implementação Python isolada já validava manifestos fechados, allowlist, quarentena, caminho/symlink, permissão, origem e tamanho; antes deste passo, não havia rota nem comando do app para publicar documentos.

## Integração do artefato no app

Foi acrescentada a operação autenticada `POST /v1/app/artifacts/synthetic-document`, com contrato de entrada Python/Rust na ordem `session_token`, `csrf_token`. A WebView não recebe esses valores: chama somente o IPC sem argumentos `g5_synthetic_document_generate`; Rust lê as credenciais da sessão e as injeta na ordem do protocolo. O parser TypeScript mantém a ordem wire declarada como contrato, rejeita propriedades adicionais e valida o documento antes de exibi-lo.

A operação cria um exemplo fixo e sintético por ação manual. Durante o lifespan do runtime, o backend cria uma raiz temporária privada com permissões de diretório compatíveis com o `umask` restritivo do launcher; guarda inputs autorizados e estado em diretórios irmãos. O registro valida o schema, tamanho, origem do manifesto, licença declarada, capacidade, escopo e principal antes de gravar `published/<id>.json`. O caminho não é controlado pela requisição. Ao encerrar o runtime, o `TemporaryDirectory` remove a raiz e o arquivo. O corpo de resposta segue limitado a 2048 bytes.

Rust confere o formato fechado, identificador, conteúdo sintético fixo, versão/hash do manifesto, licença e permissão. TypeScript repete a validação de schema e origem antes de renderizar. O teste vertical no processo supervisionado confirma a resposta pela UDS. Skills importadas seguem sem rota de importação ou promoção e nunca são executadas; a UI não cria automatizações a partir delas.

### Verificações desta subentrega

- `uv run --locked pytest -q test_skill_registry.py test_native_app_api.py::test_native_synthetic_artifact_route_is_closed_authenticated_and_temporary test_native_app_api.py::test_artifact_temporary_root_is_removed_when_runtime_stops test_native_runtime_process.py::test_supervised_fastapi_g5_vertical_flow_and_stop`: 18 passed. Inclui manifesto inválido, capacidade não autorizada, path traversal e symlink, quarentena sem execução, documento inválido, tamanho excessivo, sessão/campos extras, gravação temporária, limpeza no encerramento e caminho vertical autenticado pela UDS.
- `node --experimental-strip-types --test tests/runtimeCommand.test.mjs`: 18 passed; comando IPC sem argumentos, schema/origem e recusa de chaves extras.
- `cargo test --offline --lib`: 102 passed, 9 ignored; inclui parser de artefato, ordem dos campos de credencial e allowlist fechada da rota.
- `npm run build`: `tsc` e Vite — PASS.
- `git diff --check` — PASS.

Resultado: a geração sintética está integrada e validada automaticamente. Importações permanecem isoladas em quarentena. Não houve smoke visual.

O catálogo em `apps/web/lib/skill-catalog.ts` foi usado só como formato de contrato (`id`, `version`, `purpose`, entradas, saídas, capacidades, efeito e `synthetic_only`). As quatro skills daquele arquivo não são registradas e não são executadas.

## Allowlist

A lista é fechada:

| Capacidade | Uso |
|---|---|
| `read_synthetic` | `read-synthetic-note` e `read-registry-entry`, versão `1.0.0` |
| `generate_synthetic_document` | `generate-synthetic-document`, versão `1.0.0` |

Qualquer outra capacidade, inclusive `write_local_draft`, `build_context`, `compare_sources`, `shell` e `mcp`, recusa o registro ativo. O efeito `local_draft` da geração grava apenas o JSON já validado em `state_dir/published`. Isso não envia arquivo, não instala pacote e não altera agenda, mensagem ou repositório.

## Quarentena

Todo manifesto lido de arquivo entra em quarentena, mesmo quando o JSON é válido e a capacidade declarada está na lista. Não há promoção neste corte. Importar, ler o registro ou guardar o manifesto só faz parse de JSON. Campos `script`, `command`, `mcp`, `code` e os demais nomes executáveis são descartados; o registro guarda o nome do campo, não o valor. Symlink e caminho fora da raiz aprovada são recusados antes da leitura do alvo. Um nome igual ao de uma skill interna não a substitui.

## Limites

| Limite | Valor |
|---|---|
| Documento publicado, UTF-8 canônico | 4096 bytes |
| Manifesto lido | 8192 bytes |
| Nota `.txt` ou `.md` | 2048 bytes |

Documento malformado, origem que não fecha com o manifesto interno, permissão diferente de `generate_synthetic_document` / `synthetic`, ou resultado acima de 4096 bytes não é gravado e não aparece em `list_published`.

## Origem do artefato

O documento publicado traz `origin.skill_id`, `origin.skill_version`, `origin.manifest_sha256`, `origin.license_name` e `permission` com capacidade, escopo e principal. Cada seção tem `index` contíguo a partir de 1 e `source_id`. O número da seção aponta para essa origem declarada no próprio artefato. A licença interna registrada é a observação `nao-declarada-no-arquivo-local`: os manifestos do projeto e os cabeçalhos Python lidos não trazem SPDX. Isso não inventa uma licença.

## Licenças lidas localmente, sem rede

Não há arquivo `LICENSE` na raiz. `apps/api/pyproject.toml`, os `package.json` de web, desktop e mobile, e `apps/desktop/src-tauri/Cargo.toml` não declaram licença. `apps/api/uv.lock` e `Cargo.lock` não têm campo de licença; as licenças de FastAPI, Pydantic, jsonschema, cryptography, Tauri e dos demais pacotes desses locks não foram lidas e não são afirmadas aqui. Nenhum cabeçalho SPDX foi encontrado nos `.py` de `apps/api`.

Os `package-lock.json` locais declaram licença para todos os pacotes que listam:

| Lock | Pacotes com campo `license` |
|---|---|
| `apps/web/package-lock.json` | 598. Maioria MIT (500). Também Apache-2.0, ISC, BSD-2-Clause, BSD-3-Clause, MIT-0, 0BSD, BlueOak-1.0.0, Python-2.0, MPL-2.0, CC-BY-4.0, CC0-1.0 e LGPL-3.0-or-later |
| `apps/desktop/package-lock.json` | 61. MIT, Apache-2.0, Apache-2.0 OR MIT, ISC, BSD-3-Clause, MPL-2.0 |
| `apps/mobile/package-lock.json` | 185. MIT, ISC, Apache-2.0, BSD-3-Clause, 0BSD, BlueOak-1.0.0, Unlicense, MPL-2.0 |

As dependências diretas lidas nos três locks estão em MIT, exceto Playwright e TypeScript (Apache-2.0) e `@tauri-apps/api` e `@tauri-apps/cli` (Apache-2.0 OR MIT).

Vistos e não incorporados neste módulo: `@img/sharp-libvips-*` (LGPL-3.0-or-later), `lightningcss` e `axe-core` (MPL-2.0), `caniuse-lite` (CC-BY-4.0). Não havia, no repositório, um exemplo de skill de terceiro com o texto da licença no arquivo local. Nenhum código externo foi copiado. Este documento não promete instalação nem execução de skill.
