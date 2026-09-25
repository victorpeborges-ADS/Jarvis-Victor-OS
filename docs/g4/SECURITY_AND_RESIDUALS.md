# Segurança e residuais — G4

- Importação com a mesma chave e outro documento responde 409. O mesmo corpo devolve o resultado guardado e não duplica.
- JSON de missão inválido responde 409 `integridade do registro de missão` na leitura e entra em `corrupt` na lista. A linha não é apagada e o corpo não é ecoado.
- `fail` e `retry` são ações reais da API, especificadas no ADR 007. A aprovação humana de um artefato continua exclusivamente no modo DEMO do navegador.
- Execução aberta sobrevivente a SIGKILL vira `interrupted` no boot. `resume` é explícito e volta a exigir `mission:write` vigente.
- O commit do artefato só ocorre se a execução ainda está na fase esperada (`open` para `run_next`, `interrupted` para `resume`) e se `mission:write` continua válido naquele instante. O lock da concessão é adquirido antes da transação SQLite e só é solto depois do commit. Cancelamento confirmado antes disso não é desfeito e não recebe artefato. Revogação ou expiração confirmadas antes disso também impedem o artefato.
- A skill determinística não escreve fora do banco. Não há exactly-once para um efeito externo anterior ao commit.
- `JARVIS_TEST_PAUSE_FILE` só pausa se a variável estiver definida. Sem ela, o servidor não espera.
- GET sem Origin, principal único de login e ausência de exactly-once externo continuam limites do ambiente local. Não autorizam hospedagem remota nem dado pessoal.
