# Onboarding de contexto e limites

**Funciona agora somente com arquivo obviamente fictício:** em Missões → API local sintética → `Selecionar fonte fictícia`, escolha missão e `.txt/.md/.json` UTF-8 até 50 KB. O navegador mostra prévia, tamanho e SHA-256; confirme que o conteúdo é fictício. O servidor verifica hash, nome, tamanho, sessão, CSRF e grant `mission:write`; cria evidência pendente e registro de conhecimento `staged`. Aprove o artefato na fila, depois o conhecimento. Só então `Ver contexto autorizado` inclui o texto e IDs/hashes de origem. Duplicata de conteúdo na mesma missão gera 409; replay idêntico usa a mesma chave. Não há leitura automática de Finder, Downloads ou Drive.

| Classe futura | Política nesta versão |
|---|---|
| Fixture fictícia/sintética | Permitida após seleção explícita, escopo e duas aprovações. |
| Pessoal comum | **Bloqueada** até gate de consentimento, retenção, exportação/remoção e segurança local. |
| Financeiro pessoal | **Bloqueado**; exige gate próprio e política de minimização. |
| Saúde pessoal ou clínica | **Bloqueada**; não inserir no banco sintético. |
| Institucional MedSyn/MCID/CRIVO/SOFF | **Bloqueada**; nunca copiar para banco pessoal sem autorização adequada. |
| Tokens, chaves, cookies, `.env` | **Proibidos** na importação. |

**Futuro wizard de contexto pessoal:** selecionar fonte e domínio, prévia/redação, classificação, consentimento granular, retenção e prazo, aprovação de importação, hash/proveniência, quarentena antes de indexar, revogação/exportação/apagamento e revisão de derivação. PDF, pastas, anexos, Calendar/Gmail/Drive reais e storage seguro ainda não existem nesse fluxo. Não usar a UI sintética atual para dados pessoais verdadeiros.

**Mapa de domínios vazio para ativação:** pessoal, trabalho/comercial, MedSyn e MCID têm fronteiras distintas; nenhuma fonte real pré-carregada. As oito opções `dom_synthetic_*` da API são apenas classificação de teste, não identidades reais.
