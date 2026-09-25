# JARVIS Mobile — scaffold experimental Capacitor + React/Vite

O aceite formal do Gate 2.0-E marca este diretório como experimental. O shell web e os testes de browser podem ser executados. O APK Android não foi aceito e não deve ser tratado como funcional.

**Shell React/Vite compilado para web e projeto Android Capacitor gerado/sincronizado. APK NÃO COMPILADO ou instalado.** Android Studio/SDK, Gradle e `adb` não estavam disponíveis; não foram instalados nesta sprint.

## Escopo

- Shell sintético Agora/Conversa/Inbox/Missões, com outbox somente local no `localStorage`, limitada a 20 capturas fictícias de até 500 caracteres.
- Sem autenticação, sincronização em background, provedor LLM, conta externa, notificação ou Share Intent.
- Manifesto contém permissão `INTERNET` exigida pelo shell local do WebView; nenhuma permissão de câmera, localização, contatos ou mídia foi adicionada. Backup Android está desabilitado até existir uma política aprovada.

## Verificação que já passou

```bash
npm install
npm test
npm run lint
npm run build
npm run e2e
npx cap sync android
npm audit
```

Resultados nesta sprint: Vitest 2/2; Playwright 4/4 em viewports desktop e mobile; lint e build web passaram; `cap add android` e `cap sync android` criaram/sincronizaram o projeto; `npm audit` sem vulnerabilidades após fixar `@capacitor/cli` em `8.4.3` dentro do major 8. Nenhum Gradle/APK foi executado.

Quando Android Studio e Android SDK forem provisionados, confirme o SDK/platform local, sincronize com `npx cap sync android`, abra `android/` no Android Studio e rode um debug build/emulador com dados sintéticos. O scaffold não instala nem inicia serviço. Referências oficiais: [instalação Capacitor](https://capacitorjs.com/docs/getting-started) e [ambiente Android](https://capacitorjs.com/docs/getting-started/environment-setup).
