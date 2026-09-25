# JARVIS Mobile — scaffold documental

Estado: **BLOCKED / APK NÃO GERADO**. Nenhum app foi instalado/distribuído.

## Direção proposta

PoC Capacitor + React/Vite a partir de uma SPA isolada; não empacotar a aplicação Next.js inteira até provar a exportação estática e o comportamento offline. Primeira tela: Agora, Conversa, Inbox e Missões sintéticas; storage/outbox locais somente fictícios. Não solicitar permissões amplas. Android Share Intent para texto/URL fica fora até existir sandbox nativa e teste dedicado.

## Pré-requisitos e retomada

Java está presente, mas Android SDK/Android Studio, `adb` e Gradle não estavam disponíveis; não foram instalados. Capacitor requer Android Studio e Android SDK, com plataforma API 24 ou superior. Após provisionamento local aprovado, iniciar app isolado a partir de Vite, adicionar Capacitor, executar `npx cap add android`, `npm run build`, `npx cap sync` e `cd android && ./gradlew assembleDebug`; rodar checks web antes e testes em dispositivo/emulador sintético. Marcar o APK como debug, sem assinar ou distribuir.

Referências oficiais: [Capacitor — instalação](https://capacitorjs.com/docs/getting-started) e [ambiente Android](https://capacitorjs.com/docs/getting-started/environment-setup).
