# Segurança e residuais — G4

- Importação com a mesma chave e outro documento responde 409. O mesmo corpo devolve o resultado guardado e não duplica.
- JSON de missão inválido responde 409 `integridade do registro de missão` na leitura e entra em `corrupt` na lista. A linha não é apagada e o corpo não é ecoado.
- `fail` e `retry` passam a existir na API. Aprovar artefato continua só no DEMO.
- Execução aberta sobrevivente a SIGKILL vira `interrupted` no boot. Não há segundo worker nem reexecução automática.
- `JARVIS_TEST_PAUSE_FILE` só pausa se a variável estiver definida. Sem ela, o servidor não espera.
- GET sem Origin, principal único de login e ausência de exactly-once externo continuam limites do ambiente local. Não autorizam hospedagem remota nem dado pessoal.
