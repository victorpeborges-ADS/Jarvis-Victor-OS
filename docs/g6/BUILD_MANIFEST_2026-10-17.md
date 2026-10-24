# Manifesto de build — candidata local

Este arquivo não é o endpoint `GET /v1/version`. Esse endpoint identifica só
`protocol_version`, `runtime_kind`, `instance_id` e `build`. O valor de `build`
conferido nos dois lados do transporte é `g6-mac-002-3-locked-storage-v3`. Ele não é o SHA do Git.

O próprio manifesto fica de fora da lista de hashes: ele é o snapshot, não uma fonte.

## Identidade

- Branch: `codex/jarvis-integration-candidate`
- HEAD: `636d5bdbddcbe0b609871f7a88c64543cde7dfa0`
- Frontend desktop: `apps/desktop`, versão `0.1.0`
- Frontend web: `apps/web`, versão `0.1.0`
- Runtime: `apps/api/serve.py`
  - sem argumentos: API web, host `JARVIS_BIND_HOST` ou `127.0.0.1`, porta `JARVIS_BIND_PORT` ou `8000`, objeto `create_app`
  - `--desktop-runtime <id>`: socket `runtime.sock`, prontidão `JARVIS_RUNTIME_READY <id>`
- Build de protocolo: `g6-mac-002-3-locked-storage-v3`

## Diferenças locais

| Estado | Caminho | SHA-256 do conteúdo |
|---|---|---|
| ` M` | `apps/api/backup_cli.py` | `a02fa016d1b0fa787e5f1204806338913bd4f7b897cddfc35a642127985c7f25` |
| ` M` | `apps/api/backup_recovery.py` | `a20c21e61b3049a90be3b5f8da0408e218526c6918eb8a41e3b100f7b71c1fc8` |
| ` M` | `apps/api/e2e_mark_calendar_state.py` | `9a4586b816cc0c2c289ce6905be60f0a4521a017ea54f4a81aeafe7543e8f495` |
| ` M` | `apps/api/local_automations.py` | `dde6f211467f027e5c1b54deb280fef21e59878689655b6f11125bbb3a40720b` |
| ` M` | `apps/api/local_captures.py` | `cedb022942f3dbf98c4903d3a435d54782b688130e2e554cc4e3dbed81c50cff` |
| ` M` | `apps/api/main.py` | `d59b84e7244fef1dd7e3c9183a7fc4bd58dca1323d8e5ae9e0cd7cc0b3951262` |
| ` M` | `apps/api/memory_store.py` | `550d066587aa7139b1bf7c0cf3b4f940b809d6c257e2bfd8244b61ae19d351a5` |
| ` M` | `apps/api/native_app_api.py` | `d1bd78edc0430103f349818ac49be37003334482cdedabee06dbedf01b67f5f8` |
| ` M` | `apps/api/native_runtime.py` | `ad145a8021ec82557b166ac474ecbfc648eb42c43ee740227d2770ac395dddb5` |
| ` M` | `apps/api/test_backup_recovery.py` | `ae98a7df3b6a63cc2645dbf47bf098d1d314cbcf118f060ac5311770be2f4978` |
| ` M` | `apps/api/test_calendar_simulator.py` | `a5d3b60cc54a7d030a59aace07c9285b2fb0c481a7d25f95f0535a74146d7ddb` |
| ` M` | `apps/api/test_daily_capture_gate.py` | `6cbd4ea1d729a65e72832f36ffb55146a702602890e931c83442625e1485886c` |
| ` M` | `apps/api/test_knowledge_api.py` | `b41e21063cc6b260bbbd7af7241ec81a57de688d659f922754bd185079bb1e6a` |
| ` M` | `apps/api/test_knowledge_provenance.py` | `1e9d7226dad596363aa8d47fac9acbc8b79b0704a9edeab2a733a15d0e6b0b33` |
| ` M` | `apps/api/test_local_automations.py` | `0d60e706e359e434791019294d772d1bfa5a63c5569957c9ebba2babc9a57758` |
| ` M` | `apps/api/test_local_security.py` | `5f13e4df0ba86803712c68a691d115c9c4ad31ff5b27bbc18eeb4c2f839a4e7e` |
| ` M` | `apps/api/test_memory_store.py` | `398076a0bc79478e6c1e547dbd16453956b051ff1926bbc20e71c50aa5b788ee` |
| ` M` | `apps/api/test_mission_auth_races.py` | `ebc9b7607c88661cefddf82d06c5cb9a090c572fdb1683dbd60ae7e27e3b830b` |
| ` M` | `apps/api/test_mission_engine.py` | `db5ea7729a18fdc91c5fe100da0658015a6d5e5c3d4337931bbe2fb60f7e693e` |
| ` M` | `apps/api/test_mission_import_identity.py` | `d204447de78014fc9a5b5f111bfd0f5a2d5ebbcb7527d481ab7406a2d1f3547c` |
| ` M` | `apps/api/test_mission_read_revocation_races.py` | `a046cbd4afd6d6ff4a3a9d6744a0bc112a93e81f5d33673e19b7a8a0af12876c` |
| ` M` | `apps/api/test_missions_api.py` | `199e37913b8fe1307f4fda536a17ed6043382805f4c2f0ee87a0bc84cf1d5603` |
| ` M` | `apps/api/test_native_app_api.py` | `1aaeec3d7d1574e04e7cc5acef7ca46401fa7f3d7ff317da66c388774865a282` |
| ` M` | `apps/api/test_native_runtime_process.py` | `eaf739a2f565a40a2341cc75c39002c86819f10ca18a1e4e685e2f72e60c7418` |
| ` M` | `apps/api/test_r5_trusted_state.py` | `9264a900fa0ad0446ec303d1aa78d750732cf97a64359b0662f62e148201f28a` |
| ` M` | `apps/api/test_r6_combined_tampering.py` | `36bb8235c70cac6a939f0592a700189c19977f16b0ec4d01fa9ded9079813c6a` |
| ` M` | `apps/api/test_review_api.py` | `afe8a331a3812a7fd8074657371aeec63f0ae3dcd243989ca256a30af73c75c9` |
| ` M` | `apps/api/test_selected_source_api.py` | `d9e71f7856c84fa1f2c0b8fe56fc308d571e99b1041bf33867d08fcd00cf1ebc` |
| ` M` | `apps/api/test_workflow_executor.py` | `fa8a464d73c2d707ad65dc6d5e40bb8b2a98a8a883b1273b41cc6e3423368c80` |
| ` M` | `apps/api/workflow_executor.py` | `019ca901555fcb1d1065780f62a02231653907f6b47ae21fa472ba081a44dd0d` |
| ` M` | `apps/desktop/src-tauri/Cargo.lock` | `35c8aa2f99bb784eed77afc0c6cd8620aef5b3fdeea6e6b841c2c5dbab0063c5` |
| ` M` | `apps/desktop/src-tauri/Cargo.toml` | `46f8ea4af3bd9f0f10ad17b840d3e85349f448bc939116e16c6ee733969bd68a` |
| ` M` | `apps/desktop/src-tauri/src/lib.rs` | `43238cc40b8423825ea4390a79a294302db4f75dce0cf302188ee38c1dc0b3c9` |
| ` M` | `apps/desktop/src-tauri/src/runtime_manager.rs` | `ca7c61ed5c961f2a9f5547e22cb9e74a00ca6a92f1c30e3268e38185f027d14d` |
| ` M` | `apps/desktop/src-tauri/src/transport.rs` | `6974c70b0283d5f08747d296025565e6addb9e5e439390f6dad6c0b5e0ad00e6` |
| ` M` | `apps/desktop/src/App.tsx` | `111115d01e7870347ccc19b68afbc983fe6c93d4aa5f71b1319610d6c0763ace` |
| ` M` | `apps/desktop/src/runtimeCommand.ts` | `b006d10582a1f452f32c38b562829891bad716e625a7daa2763b3e52d45fccc3` |
| ` M` | `apps/desktop/tests/runtimeCommand.test.mjs` | `7211b0cd7f47a203ac3ba2fee6da79f98d9cda7f46b30a646209b8c46c76a0ca` |
| ` M` | `apps/web/app/globals.css` | `7b9fe1c271ac951a732e4684ca1e8d254024b39de686044cdcbfb1196500a413` |
| ` M` | `apps/web/app/layout.tsx` | `2cb988bae4a0d0b01e4f520706005c8c6bc1ae0b69c1241a926706dfe2d5cc69` |
| ` M` | `docs/GATE2_0C_2_BACKUP_RECOVERY.md` | `8666c065b1c878c18918eb05a7a3c9068f2a43fb5905080cfe9948fec58db1a7` |
| ` M` | `docs/g6/ANDROID_ARCHITECTURE.md` | `471afe6e33f4fc8b706dcf40a9c95bae61ae998bfab8c7d0c8a5431e415e04aa` |
| ` M` | `docs/g6/DECISIONS_PENDING.md` | `e72f7b86a48a5cd10c0956b31d1a847d552ec4824933d5817c4f88f6d27ef0da` |
| ` M` | `docs/g6/LOCAL_AUTOMATIONS.md` | `fdd9231c7937b9a2cf0a9d41d9e0f4a0d0bd14017273c799b2b95ff3d5126d56` |
| ` M` | `docs/g6/WORKFLOW_EXECUTOR.md` | `1d85a851dbbc9a53c7c00caea9bf324757215d6295c92eb2f71433b19769fad3` |
| ` M` | `docs/g6/g6-3/MAC_003_APPLICATION_PROTOCOL.md` | `eb0003cd537c04030428db62719ca4ffe2799443a4c0ae11ef4c72bd4871bfab` |
| `??` | `apps/api/api_test_support.py` | `ca5b0e1f17f4d51cb4f1a78c8aa835783d11369966224cc6599ff5cf6e71a011` |
| `??` | `apps/api/approved_effect.py` | `51d94459d61cfa910c4d94430db5e77544bc7936a33d1097510c0f97fd21494c` |
| `??` | `apps/api/approved_ingestion.py` | `f4ad63466a3166d8741aea25a99322b77c4e30f50ba4172be66eda93cb51439b` |
| `??` | `apps/api/artifact_store.py` | `af3d337d39272e7b4131453e4449e2a0be51d1d4e1bc15210fda616f1fcfda41` |
| `??` | `apps/api/conftest.py` | `72ff9ab5c9ae996ebc3237081cbda9165bcbc41e3fd05380ea5ab177b0856f3d` |
| `??` | `apps/api/conversation_continuity.py` | `023c1595ed22fa84f289bd3171173d0ef4d6e100f70a6cec75fba35acbd6695a` |
| `??` | `apps/api/conversation_gateway.py` | `8846df5f2d2e5d503a561c403d9d55a449e82423b680b0e127a486c84cfe4e92` |
| `??` | `apps/api/database_leases.py` | `12f1b21cce4edf0d8d507881875ce3516bd12d47c76ef63f8f5c9d4e5e7925e6` |
| `??` | `apps/api/document_pages.py` | `9c4ef6561a22d813ab8059efe18b85692228b93d0ec7957ed45fdade3acde3f5` |
| `??` | `apps/api/export_build_manifest.py` | `1dfac3790d05cf366895430b060fd4a6e9d185122f920821eb8aa8bd20aac7e7` |
| `??` | `apps/api/fixture_connectors.py` | `4df3d6cfa6e42299bd820a2c04c74bef35a9c8588728040d52391eef9d41623e` |
| `??` | `apps/api/fixtures/automation_validation_error.txt` | `75fe2e680be00d231391775c49d27496963497cf799b52c2a6d72790c5f7be33` |
| `??` | `apps/api/fixtures/connectors/calendar_all_day.json` | `d5a9e8398f49b72faabe13a522705d0a67c7406c9cc13a9b6a8b600130a24d3e` |
| `??` | `apps/api/fixtures/connectors/calendar_current.json` | `4f52294935ab39fc726af65411e819e7cb818ce45fc557689b160a8a36fb8862` |
| `??` | `apps/api/fixtures/connectors/drive_current.json` | `c56afa92c78fd2f9ee9fb59691a525dfeed567a92e434086863c16e72f19fc9f` |
| `??` | `apps/api/fixtures/connectors/duplicate.json` | `35b2d9e87554d053e1a23a9480ae6873cd96695a8b064eec0f36362b06130c10` |
| `??` | `apps/api/fixtures/connectors/github_current.json` | `d4907f8db0be8ea8b1b63626336076fe9fd171f91ac20934a7e9f4524b9c0902` |
| `??` | `apps/api/fixtures/connectors/gmail_current.json` | `ec1bb1402f56dbc3c41e6e5ba729d2da8884377a3460921cdab610789b0bc584` |
| `??` | `apps/api/fixtures/connectors/large.json` | `a4bc4fd3d7ac908e4c64768c5f528774325489aef9c40a743a28c35d09615a49` |
| `??` | `apps/api/fixtures/connectors/local_url.json` | `3d692e138bf872765dfbbb72c690c35987bc94537d0ebefbdd69fcb069c22fde` |
| `??` | `apps/api/fixtures/connectors/malformed.json` | `a6fb08fda1acb957b6116bd37811a1fe41a01611c0631edbf786d6889a27a55c` |
| `??` | `apps/api/fixtures/connectors/malformed_extra.json` | `93118b8927615d0ba3d286e77f6126dde30cd9e96bff2fc3058526d6a213964c` |
| `??` | `apps/api/fixtures/connectors/malformed_item.json` | `0a9b0f0c58469c97309edb000dadb793de4a3b2e56c71e31a783051afbaef560` |
| `??` | `apps/api/fixtures/connectors/mcp_current.json` | `38c42e6ff0ae1059e144ecc1bdc79df9cde79fe21a62baec0c13284803e7c94e` |
| `??` | `apps/api/fixtures/connectors/mcp_malicious.json` | `06180d07c0306e4338941d87d473bb44d20311f393c62e82479b4c88622ece95` |
| `??` | `apps/api/fixtures/connectors/mcp_missing_schema.json` | `0a629e79771cd5e1cbaecdc8c192f9daa1b9e9c76a5e662de1567410573753bc` |
| `??` | `apps/api/fixtures/connectors/redirect.json` | `cfd408004ff31cb0b68ed09f1cb749626e2cfc35614a53afc70585d98e374588` |
| `??` | `apps/api/fixtures/connectors/revoked.json` | `9f0c92e56a7c063c8fa60e673874d846005b1dd5c32b05a4bf42133b92327443` |
| `??` | `apps/api/fixtures/connectors/stale.json` | `a53aa44026ce2320a7062bc3a5bfd0c16fc84e9555ddbe1fcefb28ea6342b4d8` |
| `??` | `apps/api/fixtures/connectors/timeout.json` | `a447b7bca845cc1a9eb8ef0a5fddf91c05685c85f415f18c18f54da509aea74e` |
| `??` | `apps/api/fixtures/connectors/untrusted_gmail.json` | `e5ca518d0e45e64637e1d2272b9fcadc337c154fc69c0ee04bff1db62449cbf8` |
| `??` | `apps/api/fixtures/scope_invalid_error.txt` | `b5773d3091bf2f50d4643bab7182219d4ca16e93988f4bb78ffefe2dde33b82a` |
| `??` | `apps/api/fixtures/workflow_page_v1.txt` | `dee2b5b5c3df0dd39057adb694eab48213eb2801c7cbc94c1569b9eb817010a3` |
| `??` | `apps/api/grounded_read.py` | `ee906742abedd524518245fd1ba84a35f8c0037d83cd75eba90140b3a4eda524` |
| `??` | `apps/api/learned_proposals.py` | `59f81cc8f87736c71a7667f05eb3199ce76688f97bc49fcaf0ffc63f9ccf6ca0` |
| `??` | `apps/api/memory_categories.py` | `3ba90a4aab214037acdc47ec50ab834dd5e3ef249af21834b4bb490d250de830` |
| `??` | `apps/api/memory_deletions.py` | `7f10bc24b9a7c301d58da136bd60ee38df50a41f238bc51cfec26128b1dfe509` |
| `??` | `apps/api/migrations/0021_effect_approval_outbox.sql` | `b3b4ccdb14e353e57863d60ad975da87612a7ca392131ebbd46ffd3bcd3b6e94` |
| `??` | `apps/api/migrations/0022_memory_categories.sql` | `c6a07f619edc6ae2270a6606c70cb54eada10e89824d25589b91fe39f2b8cca7` |
| `??` | `apps/api/migrations/0023_conversation_continuity.sql` | `7e8aeda214d58a57e77cd71d258d5cb18e01512e077c79ea71e545ff5449e7c9` |
| `??` | `apps/api/migrations/0024_approved_ingestion.sql` | `1a019bfed7e5363306163cc966ca06747955ea9fbd625532168d5c22c7606328` |
| `??` | `apps/api/migrations/0025_prepared_effects.sql` | `a3c7aadf4ebb15d227d6af2095a54ab59aba087b170294ac8a0387bef51aa749` |
| `??` | `apps/api/migrations/0026_memory_deletion_tombstones.sql` | `3f0e939c261367d33c5184f013f2ff603f9c9734367d06e8d1be8b9515a309dd` |
| `??` | `apps/api/migrations/0027_memory_capture_revisions.sql` | `8c92f72f113b01251366c7b88989fb087d82d08de0f3ef6b57b43d0785caca23` |
| `??` | `apps/api/mobile_sync.py` | `25d68195c9c31003cbab16740b55df472d93b7a04ea845ef8794708c0c18b290` |
| `??` | `apps/api/package_rehearsal.py` | `01b2f1d3d9c9cbe89a0276e9a7744586d168d27170689a5fb9c2b676ef8c2d43` |
| `??` | `apps/api/read_only_tool_loop.py` | `118f2da7ba569a89b941453cfdb4051c170609d1923f5c71608c7c62b5570c25` |
| `??` | `apps/api/real_provider_eval.py` | `9d2d16b8a7c7564a93bd69ca08f140e1daa20553bc21de00cfe7e90a55fd1119` |
| `??` | `apps/api/restore_activation.py` | `50a586123806f1b72b114406a6967fee79951ebccfb54dfd665214191ab490ab` |
| `??` | `apps/api/sealed_database.py` | `719508a0dc6898845b47783d2af957f32959a7afe60594fab3cf93eea4e985da` |
| `??` | `apps/api/skill_registry.py` | `345eac5933cb0a808754c56c9bba9478a2bfa3b760abbfd338014c5dd1dcf9b2` |
| `??` | `apps/api/test_conversation_gateway.py` | `cfa76fa9b20cfe4172d54fb264a0e7360e9eb05b5759705718e32f20d09eebe2` |
| `??` | `apps/api/test_fixture_connectors.py` | `f0483dbdc3b9d49f69dee16d7a088542dcf2af2ede0610a935576cce06ded386` |
| `??` | `apps/api/test_front10_mobile.py` | `733f172c51a141b188f7b1fa68017ba64414eaab3de67e6c5b217c9ec5a56885` |
| `??` | `apps/api/test_front2_continuity.py` | `afcd1696638f03f8f3fcc64d1df41f69150e4b9d481ea92c4a17d7888b690bca` |
| `??` | `apps/api/test_front4_ingestion.py` | `06ec348f1b89a10aa05acc885296127f336d569853c43780b56da6a60c37baa1` |
| `??` | `apps/api/test_front7_effects.py` | `0d080a735725fa029a3f8dcf3b31f84afece8774155cd046ade9e4b745a1ec95` |
| `??` | `apps/api/test_front8_package.py` | `6a17a4b176370c496c45eafb9c46b6dedc9e0b1058dae0d933bd128efd74094e` |
| `??` | `apps/api/test_front9_voice.py` | `3fd2d5c8695bee6e9de587fa83e7c2512e961405b6a0fc09ae53e89950bf756a` |
| `??` | `apps/api/test_grounded_read.py` | `c397aa7b66a280ab1b5a6637e89d1ccbc712f6b2f98b6b892ede0b5faf9cab6d` |
| `??` | `apps/api/test_memory_categories.py` | `098de660cfb0131786c774dbf42317deee17dbaa92d4e4d1827cd9d9da60f136` |
| `??` | `apps/api/test_read_only_tool_loop.py` | `0cfd76cf8ca71d2c0c023df25901edf44027c7e5e27143212f422b605eb41f8d` |
| `??` | `apps/api/test_real_provider_eval.py` | `f658752fd7ec2d837d348aceff82b8a4fbae72fccf9ae24bf7bd40a9a3c64620` |
| `??` | `apps/api/test_restore_activation.py` | `e1444e7b876f5355e9e65409fd008a9abb17296d37bebb81990ba583f0fe456c` |
| `??` | `apps/api/test_restore_activation_review.py` | `4fb5c84557fd4f5604f02de019bf285bf4d8f7bf3def14337f0118a481cc0bb5` |
| `??` | `apps/api/test_sealed_database.py` | `f882b4c7d3834a9cc9b210cbcc0b56cb4ab3e847573fc077bd04ad1550437cab` |
| `??` | `apps/api/test_sealed_process_recovery.py` | `615a804617c8e033105d07311c01d99b5aca8efbffbcdf6c169689494dc5ff47` |
| `??` | `apps/api/test_skill_registry.py` | `8f65b9a2ceb95ff999ac34681f43767584677bec995709b3c17d41b06e6f4ac6` |
| `??` | `apps/api/voice_session.py` | `c1a19a083aa59229c9f65501204f43e9639256ef833d7cc32c7bd1b97637752d` |
| `??` | `apps/desktop/src-tauri/src/runtime_manager_keychain_test.rs` | `0f260eeb7bffbc3c0d8fd4048e25ed3849fd461525ea033124fea7eea27de84c` |
| `??` | `apps/desktop/src-tauri/src/storage_keychain.rs` | `93132166870b469d4c6049f2c8990a6fd3714cc980999d307ddd0dc1d8462cd4` |
| `??` | `apps/desktop/src-tauri/src/storage_keychain_native_test.rs` | `21afee64b97d3f9a2688b7ff966407b8060e1d6b57fcc3facbdfe38874b0c911` |
| `??` | `apps/desktop/tests/workflowHistory.test.mjs` | `c39b70ae846d583e0ef2fc27a0f98a0d8a4f95ea7a53068e5667861417e00c16` |
| `??` | `apps/web/scripts/offline-loopback.sb` | `0d89663a5f6fb303735f9a0d9926151a71e6d85f732c9337797eadf0d83161bf` |
| `??` | `docs/adr/012-local-purge-export-and-backup-resurrection.md` | `93701f81533581f1773f1c0b13df946709c26c1d4ae2646673298d7cd5ab55ee` |
| `??` | `docs/adr/013-active-sqlite-encryption.md` | `9c29224900671f69650e6801f6a520ee2a869b52ccefbd8c8a3ee5e84b326324` |
| `??` | `docs/adr/014-push-to-talk-local-bloqueado.md` | `e87797991831a7215632d6ad5fdfacdd81457d1327449199713ad8d7fe73ac08` |
| `??` | `docs/adr/015-at-rest-inventory.md` | `10ba2c503c95c348a3961d75df7c41c926d8a30231b0ce2d83eed983b64954fe` |
| `??` | `docs/adr/016-mobile-sync-rehearsal.md` | `326ca87e1a57a748f40f2cb7cec9f6cb26697165c85a5723a7801c2b8ba0ed7c` |
| `??` | `docs/g6/EFFECT_APPROVAL_OUTBOX_2026-10-17.md` | `1d504104cc97b30b14b32e794b34b9c71cbb463fc769f33dc37f1bb33781c1c1` |
| `??` | `docs/g6/FAKE_PROVIDER_CONTRACT_2026-10-17.md` | `50b4f2e15966bba51a44c9b2c07f26a2fabec4fa1ea499caf5e2593d78d93939` |
| `??` | `docs/g6/FIXTURE_CONNECTOR_CONTRACT_2026-10-17.md` | `ab325c78fb42bd63087a23f28843110ce47728675c8a4be205c8e4a03f2f864d` |
| `??` | `docs/g6/GROUNDED_READ_AND_REAL_PROVIDER_PROTOCOL_2026-10-17.md` | `9037e75bee5402ab4bc82650fa58f50c8b8aade2b96839775f404f1f78c51bab` |
| `??` | `docs/g6/LOCAL_AUTOMATION_ERRORS_2026-10-14.md` | `8be54c2a144384d2e41fdd417cfd501f265e99242b580fc9115391f82a6a1598` |
| `??` | `docs/g6/NOTA_BLOQUEIOS_NUCLEO_MAC_2026-10-17.md` | `953773c872d5221ec03570701adf6cfda04f176ff9ae0ec7e15fd244d49c8293` |
| `??` | `docs/g6/PLANO_ATIVO.md` | `31c0caee00fde680e72c1ff7449eee20eb8b55dd874afc76beff3c0dda5924ba` |
| `??` | `docs/g6/REAL_PROVIDER_EVAL_2026-10-21.md` | `dd49e74968acb4594425ef8b13cdc50cfa95bcefc2638ed36d67450768aff459` |
| `??` | `docs/g6/RESTORE_ACTIVATION_2026-10-16.md` | `7239568180c7c954d407313ba2fb59ad056b09c84f3a2b853f5e525ff1f91b07` |
| `??` | `docs/g6/SKILL_REGISTRY_2026-10-17.md` | `8628f834a7d0e0868f7bf8d7232dbadd2cc467f13371752a87fa4abc4d2d8c77` |
| `??` | `docs/g6/WORKFLOW_HISTORY_PAGINATION_2026-10-14.md` | `9f3d5788747df7ff1a2d3b632e28cb289e84644b1931e23dc9f22b122747e24f` |

Nada nesta lista foi staged por este gerador. Banco diário, conta e efeito externo não entram.
