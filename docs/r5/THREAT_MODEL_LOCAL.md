# R5 — Modelo de ameaças local

## Escopo

Aplicação local Jarvis, API FastAPI loopback, SQLite privado fora do repositório, um processo coordenador, fixtures sintéticas e grants/sessões voláteis. O navegador local não é autoridade para owner, domínio, proveniência ou aprovação. Esta análise não cobre OAuth, fontes reais, multiworker, rede pública ou dados pessoais.

## Ativos e controles

| Ativo | Controle esperado |
|---|---|
| Bytes e metadados da fixture | Catálogo imutável do servidor e hash SHA-256 recalculado |
| Relação fonte–missão–domínio–owner | Prova relacional completa em cada superfície de leitura e antes de decisão |
| Decisão de revisão | Snapshot imutável e ledger local append-only correlacionados por versão/hash |
| Contexto de missão | Apenas conhecimento cuja origem e aprovação atuais sejam canônicas |
| Sessão e grants | Estado volátil em memória; checagem de owner, recurso e domínio no servidor |
| Banco e backups | Diretório privado, permissões restritas, WAL e validações de integridade existentes |

## Atores e capacidades consideradas

- Usuário da UI tentando editar campos escondidos ou reenviar payload antigo.
- Cliente local que constrói importação com decisão, owner, missão, domínio ou hash falsos.
- Processo local com capacidade de editar SQLite, corromper ligações ou restaurar backup antigo.
- Duas requisições concorrentes de leitura, aprovação, reconciliação ou importação.
- Arquivo legado legítimo, desconhecido ou parcialmente corrompido durante upgrade.

## Ameaças e respostas

1. **Forjar metadados de origem** (`fixture_id`, classificação, hash, catálogo, proveniência): reconstruir a prova completa e colocar divergências em quarentena; esconder bytes e metadados da resposta.
2. **Religar fonte a outra missão/owner/domínio ou conhecimento**: verificar todos os vínculos em conjunto; manter escopo owner no servidor; ocultar artefatos órfãos ou mal ligados.
3. **Forjar aprovação no documento ou na tabela de revisão**: derivar decisão apenas do ledger local íntegro e do snapshot/versão atuais.
4. **Importar `approved` ou decisão equivalente**: rejeitar a missão inteira como item importado não confiável; não escrever missão nem ledger; contexto e transição continuam ausentes.
5. **Repetir uma aprovação antiga após revisão do artefato**: conservar a verificação de revisão/hash/versão existente; não relaxar decisões para versões antigas.
6. **Corrida com escrita/reconciliação**: serializar writers e formar as projeções a partir de uma leitura transacional coerente. Probes exercitam ambas as ordens de read/reconcile.
7. **Upgrade de base legada**: manter registros; reconstruir somente candidatos explicitamente registrados pela migração. Fixture byte-exata pode ser reconciliada após prova de todos os vínculos; fonte desconhecida ou alterada é preservada em quarentena.
8. **Concorrência de importação/idempotência**: chave e corpo são verificados no mesmo limite transacional; submissões idênticas produzem um registro e replay.

## Invariantes operacionais

- Read endpoints continuam exigindo os grants locais atuais e filtros no servidor.
- A classificação não é autorização; aprovação não é proveniência; domínio é escopo, não concessão.
- Nenhuma sessão/grant local vira credencial remota ou estado durável.
- Locks/transações seguem a ordem existente do store; reconciliação não realiza chamadas externas.
- Falha de prova é fail-closed e minimiza a resposta. Quarentena não apaga os registros de auditoria.

## Riscos residuais

- Um agente com controle administrativo do processo, sistema operacional ou arquivo de banco pode substituir código, apagar dados ou negar serviço. R5 detecta inconsistências de dados, não protege contra o administrador da máquina.
- A coordenação é de processo único; várias instâncias independentes não são suportadas.
- Revalidação não impede um leitor local autorizado de copiar conteúdo enquanto a prova ainda é válida.
- Sessões/grants são locais e voláteis; não equivalem a identidade forte nem devem ser expostos fora do loopback.
- Não há aceite formal G5 nesta candidata.
