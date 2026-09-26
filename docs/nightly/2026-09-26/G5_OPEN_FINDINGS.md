# Achados G5 ainda abertos

| Gravidade | Achado | Estado e próximo passo |
|---|---|---|
| P1 | O G5 congelado `4931c56` possui as falhas de sessão, grant de escrita, versão e hash descritas em `G5_AUDIT.md`. | **ABERTO no candidato congelado.** Não alterar esse SHA. A branch noturna contém correções testadas; exige revisão independente distinta antes de aceite. |
| P2 | Revisões legadas que perderam o snapshot original antes da migração 0010 podem ficar ilegíveis. | **MITIGADO por falha fechada.** Oferecer recuperação editorial explícita a partir do original selecionado, sem inventar conteúdo histórico. |
| P2 | SQLite local não fornece integridade criptográfica contra administrador que substitua o arquivo inteiro e histórico de migrações. | **ABERTO.** Definir modelo de ameaça e assinatura externa se houver requisito de prova contra adulteração local privilegiada. |
| P2 | Sessões e concessões em memória impedem multiworker, API remota e acesso direto do Android ao Mac. | **ABERTO por arquitetura.** Requer novo gate para identidade/distribuição. |
| P2 | O teste de `Host` exato e inspeção nativa VoiceOver/Android ainda não foram concluídos. | **NÃO TESTADO.** Executar em auditoria externa antes de exposição fora de loopback. |
