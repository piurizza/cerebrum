# Changelog

## [0.5.0](https://github.com/piurizza/cerebrum/compare/v0.4.0...v0.5.0) (2026-10-23)


### ⚠ BREAKING CHANGES

* ignore hidden folders and files when indexing and watching the vault ([#68](https://github.com/piurizza/cerebrum/issues/68))

### Features

* **auth:** sign in with an OpenID Connect provider ([#65](https://github.com/piurizza/cerebrum/issues/65)) ([ac47a0f](https://github.com/piurizza/cerebrum/commit/ac47a0fabe46aa76a66d9b7ca777bc45aac66351))
* ignore hidden folders and files when indexing and watching the vault ([#68](https://github.com/piurizza/cerebrum/issues/68)) ([f772e2a](https://github.com/piurizza/cerebrum/commit/f772e2a5ccfc9a7131cc099b77b75b4eead8932d))
* make the accounts database location configurable (CEREBRUM_AUTH_DB_PATH) ([#64](https://github.com/piurizza/cerebrum/issues/64)) ([fdb1ee6](https://github.com/piurizza/cerebrum/commit/fdb1ee632755e8cab4f56e1f4970ea7750f90434))
* read-only vault mode (CEREBRUM_VAULT_READ_ONLY) ([#66](https://github.com/piurizza/cerebrum/issues/66)) ([7c29937](https://github.com/piurizza/cerebrum/commit/7c29937cdd06ae19ec66cc4d08b8cf52bc7a7e2c))


### Bug Fixes

* keep a password admin, start a second read-only instance, reject hidden note folders ([#70](https://github.com/piurizza/cerebrum/issues/70)) ([37c8c45](https://github.com/piurizza/cerebrum/commit/37c8c45814bccb14b20f4b5c0b39b96894c97f2f))
* save the loaded note on Cmd+S pressed right after it opens ([#69](https://github.com/piurizza/cerebrum/issues/69)) ([e7b1078](https://github.com/piurizza/cerebrum/commit/e7b107880b5ec14ee878ed304bc037e27fc40749))

## [0.4.0](https://github.com/piurizza/cerebrum/compare/v0.3.0...v0.4.0) (2026-10-21)


### Features

* understand [[wikilinks]] and optionally write them ([#61](https://github.com/piurizza/cerebrum/issues/61)) ([54a8015](https://github.com/piurizza/cerebrum/commit/54a80154d3dd70cbd1654fb13f665ec3b986f6f0))


### Bug Fixes

* label the rename form's final button Confirm ([#62](https://github.com/piurizza/cerebrum/issues/62)) ([95fc893](https://github.com/piurizza/cerebrum/commit/95fc893550ba33ecbdfec0a91c62d160c139f96d))

## [0.3.0](https://github.com/piurizza/cerebrum/compare/v0.2.0...v0.3.0) (2026-10-16)


### Upgrading from 0.2

Two defaults changed. Check `.env` before running `docker compose up -d`:

* **The ports moved from 8080/8443 to 7811/7812.** To keep your old address, set `CEREBRUM_PORT=8080` and `CEREBRUM_HTTPS_PORT=8443`. If you installed Cerebrum on a phone, keep the old HTTPS port: the installed app and its offline copy belong to that exact address, port included.
* **The ports now listen on this machine only.** If you open Cerebrum from other devices, set `CEREBRUM_BIND_ADDRESS=0.0.0.0`.

New installs with the one-command installer aren't affected.


### Features

* **desktop:** connect to a server on the same computer without asking ([#57](https://github.com/piurizza/cerebrum/issues/57)) ([4fd5628](https://github.com/piurizza/cerebrum/commit/4fd5628fba2635b0da9668bf5b2c25214491e1c8))
* install Cerebrum with one command, no clone, on x86_64 and arm64 ([#56](https://github.com/piurizza/cerebrum/issues/56)) ([56a2a34](https://github.com/piurizza/cerebrum/commit/56a2a346059cd83cbb18f8558ebbb2615ad9b8f3))
* use 7811/7812 as the default ports instead of 8080/8443 ([#55](https://github.com/piurizza/cerebrum/issues/55)) ([337f9cc](https://github.com/piurizza/cerebrum/commit/337f9ccb424e876af862f61aa72ab09f373368e8))

## [0.2.0](https://github.com/piurizza/cerebrum/compare/v0.1.0...v0.2.0) (2026-10-16)


### Features

* **desktop:** release a universal macOS .dmg ([#51](https://github.com/piurizza/cerebrum/issues/51)) ([91ec45d](https://github.com/piurizza/cerebrum/commit/91ec45d2e414f2265fd6c2ba460e98605bcea84c))
* **desktop:** Windows installer, with a CI smoke test that installs and launches it ([#54](https://github.com/piurizza/cerebrum/issues/54)) ([2477dcb](https://github.com/piurizza/cerebrum/commit/2477dcbc29c94c3bb12d00c000cb8c2ff25a2567))

## 0.1.0 (2026-10-16)


### Features

* add a delete action for notes ([#10](https://github.com/piurizza/cerebrum/issues/10)) ([7c32ce2](https://github.com/piurizza/cerebrum/commit/7c32ce2cc675ad7742bd5f9488119e57948a81f9))
* add cross-vault task view ([#31](https://github.com/piurizza/cerebrum/issues/31)) ([c5e5420](https://github.com/piurizza/cerebrum/commit/c5e54204ad065061b89a048282eaff7852deaf1c))
* add note templates to the "+ New note" flow ([#30](https://github.com/piurizza/cerebrum/issues/30)) ([f7ce6ca](https://github.com/piurizza/cerebrum/commit/f7ce6ca695eda7ac565798191bf42a4cba35b3d9))
* add one-click "today's note" entry point ([#29](https://github.com/piurizza/cerebrum/issues/29)) ([2a35d71](https://github.com/piurizza/cerebrum/commit/2a35d710b88237182d27a7c85fde728a782211c4))
* **auth:** backend authentication -- accounts, sessions, personal API tokens, admin capabilities ([#17](https://github.com/piurizza/cerebrum/issues/17)) ([996f2a1](https://github.com/piurizza/cerebrum/commit/996f2a12bdefdf0f4c7cbccc19ffbac8d84f1fad))
* **backend:** add OpenAPI schema export script ([fca2842](https://github.com/piurizza/cerebrum/commit/fca2842eab1b338518f7b2aaba83c1c3bbeca9d1))
* change your password from Settings ([3bffa11](https://github.com/piurizza/cerebrum/commit/3bffa1146fb53bdb1e5f77685b47641f5d7e6711))
* create a new note from the UI ([2987a6f](https://github.com/piurizza/cerebrum/commit/2987a6f1bd59431e0f824059c9f5f1a3863d1039))
* **deploy:** serve HTTPS with a self-signed cert (U1) ([ebb8d65](https://github.com/piurizza/cerebrum/commit/ebb8d657e197a7a80002b3c1ceab882c909450be))
* **desktop:** add native Linux desktop client ([#33](https://github.com/piurizza/cerebrum/issues/33)) ([d02b499](https://github.com/piurizza/cerebrum/commit/d02b499cf315cf8340f8e262f5912aa3bd74c181))
* **desktop:** auto-connect to a configured default server on first launch ([e1b7fa9](https://github.com/piurizza/cerebrum/commit/e1b7fa9ca0d056f08b2741fb8e83a4d7b2b4a1b7))
* **desktop:** navigate through on failure for previously-connected URLs (U5) ([114b7f9](https://github.com/piurizza/cerebrum/commit/114b7f9ebf0285e415c96f49a8a107a87a8bfc95))
* filter notes by tag in the sidebar ([#13](https://github.com/piurizza/cerebrum/issues/13)) ([1f95467](https://github.com/piurizza/cerebrum/commit/1f95467039ade00003695afacb72637bb1d71fd3))
* **frontend:** broaden mount cache-restore + optimistic seed + logout tombstone (U4) ([eff73c6](https://github.com/piurizza/cerebrum/commit/eff73c65cd5b86976e96f9d6202109c19cfec2f7))
* **frontend:** classify refresh 401/403, and GET-scope the 5xx offline signal (U2) ([68b1d59](https://github.com/piurizza/cerebrum/commit/68b1d5959ff1888183ae756856c24ca0e3d628ea))
* **frontend:** defense-in-depth offline guards on NoteBrowser create flow (U5) ([84d8e77](https://github.com/piurizza/cerebrum/commit/84d8e774e692f2260ee21d23c494e3e18b7791e8))
* **frontend:** full-screen modals + 44px touch targets on mobile (U3) ([c2523e4](https://github.com/piurizza/cerebrum/commit/c2523e4690c0bcac00aa1e45f1dbf21e872282d5))
* **frontend:** generate TypeScript types from the backend OpenAPI schema ([5bd6782](https://github.com/piurizza/cerebrum/commit/5bd678238dbf4fea680038529e6699ba002fe7d0))
* **frontend:** installable PWA (Phase 2 — U5-U12) ([16cf23a](https://github.com/piurizza/cerebrum/commit/16cf23aaa46594253ce9716326cccbd96c5ece70))
* **frontend:** iOS + theme-color meta; dynamic theme-color (U7) ([6655389](https://github.com/piurizza/cerebrum/commit/66553890bb4feeb34591ea471ca84878157abf1f))
* **frontend:** iOS Add-to-Home-Screen hint (U10) ([70ce249](https://github.com/piurizza/cerebrum/commit/70ce249d5cef738460893b777522c9c77d909cdd))
* **frontend:** mobile top bar + off-canvas drawer (U2) ([3c8c4ed](https://github.com/piurizza/cerebrum/commit/3c8c4ed4601b81733a434b7f1617d31f1a7a5eac))
* **frontend:** mobile viewport meta, 100dvh, breakpoint scaffold (U1) ([b5d86b0](https://github.com/piurizza/cerebrum/commit/b5d86b0adcc5a09ccbc3252fb805b82ca946a2a4))
* **frontend:** mobile-responsive layout (Phase 1 — U1-U4) ([d2e4437](https://github.com/piurizza/cerebrum/commit/d2e443775f81902804687cb2864a063011a6fb15))
* **frontend:** note editor + graph at phone width (U4) ([5ec0cd2](https://github.com/piurizza/cerebrum/commit/5ec0cd2ffa797eca5c8665a9e1b5463ba8e82cf8))
* **frontend:** offline context, read-only enforcement, auth restore (U4) ([cc09f50](https://github.com/piurizza/cerebrum/commit/cc09f508b7a7d946490e3fa4186c4a385712b88b))
* **frontend:** precache the app shell with a service worker (U2) ([fa8fb4d](https://github.com/piurizza/cerebrum/commit/fa8fb4d67a890df5ca6c188e90c244efb04d80db))
* **frontend:** proactive full-vault sync + API runtime caching (U3) ([9215be5](https://github.com/piurizza/cerebrum/commit/9215be53e8446e0e52fe5be8906a9c4795d19206))
* **frontend:** PWA icon assets (U5) ([a8925c6](https://github.com/piurizza/cerebrum/commit/a8925c63ae8d3a8998d8f31352a76c0dc6374723))
* **frontend:** PWA manifest + prompt-mode SW config (U6) ([6c803f5](https://github.com/piurizza/cerebrum/commit/6c803f599788eab4c4334b30eb5d796797d21f1d))
* **frontend:** refresh the note list when the window regains focus ([b0dab0e](https://github.com/piurizza/cerebrum/commit/b0dab0e0455e7783d9d153fb4cef9285364fac4d))
* **frontend:** render mermaid code blocks as diagrams in the preview ([90d1164](https://github.com/piurizza/cerebrum/commit/90d11649461e578d42ec2a08de74f0d3fe051647))
* **frontend:** serve cache on a 5xx and mark cache-served responses (U1) ([2e7e173](https://github.com/piurizza/cerebrum/commit/2e7e173c30274dc9f84974d4a2cd4c828fd22978))
* **frontend:** session-established marker + one-shot logout tombstone (U3) ([2338b04](https://github.com/piurizza/cerebrum/commit/2338b049f2c9ee427ed106898de525d2c600e368))
* **frontend:** standalone detection + Android install control (U9) ([8f2726a](https://github.com/piurizza/cerebrum/commit/8f2726aecc3a05f8acebdbe4633d2afdaac2fae7))
* **frontend:** SW reload prompt; move registration to RootLayout (U8) ([633a9b4](https://github.com/piurizza/cerebrum/commit/633a9b4c3d9591eb370fd947c0f93985e2a8821b))
* full-text search notes by content ([#12](https://github.com/piurizza/cerebrum/issues/12)) ([d0715eb](https://github.com/piurizza/cerebrum/commit/d0715eba1dc0d1f4cdb694f2e39ed64bc563e172))
* generate frontend API types from the backend's OpenAPI schema ([4b821a4](https://github.com/piurizza/cerebrum/commit/4b821a4512305d7229706bf936634fde68d1d078))
* **index:** add PendingRenameCache primitive (U2) ([c1aa6f0](https://github.com/piurizza/cerebrum/commit/c1aa6f02dbaefe5a9334c0b348c06f437f091535))
* **index:** make the backstop rescan cross-window-rename-aware (U4) ([273eb9c](https://github.com/piurizza/cerebrum/commit/273eb9ced5653f0e443c2037f8971e5ba0600672))
* insert a link to another note via [[ autocomplete while writing ([#14](https://github.com/piurizza/cerebrum/issues/14)) ([e75ddbe](https://github.com/piurizza/cerebrum/commit/e75ddbe70b3e9587b654bc096dffbe6edaf93a08))
* let the rename action update a note's title, not just its path ([#8](https://github.com/piurizza/cerebrum/issues/8)) ([f7f5200](https://github.com/piurizza/cerebrum/commit/f7f5200fbac54b4cc46fac2edd51fa49996f507d))
* link-aware note rename + collapsible folder tree ([#7](https://github.com/piurizza/cerebrum/issues/7)) ([3452386](https://github.com/piurizza/cerebrum/commit/3452386c779383a79eb57caa7ae20e4929e86e45))
* markdown preview mode for the note editor ([312b6d1](https://github.com/piurizza/cerebrum/commit/312b6d1eb7287495e64c797f3a47da5316ef2b42))
* MCP server for remote LLM access to the vault ([#16](https://github.com/piurizza/cerebrum/issues/16)) ([e1d4f10](https://github.com/piurizza/cerebrum/commit/e1d4f10165eb7966b3e6a6ec420d48733124276b))
* **mcp:** append-to-note, edit-note and delete-note tools ([8298ac2](https://github.com/piurizza/cerebrum/commit/8298ac27fc9488cd619e15a846a15fe115afa045))
* offline session continuity -- don't strand a cached vault at the login page ([4d1bab1](https://github.com/piurizza/cerebrum/commit/4d1bab17ce6d04fc82d97e6be3408e0d1500fee5))
* paste-to-embed image attachments ([#19](https://github.com/piurizza/cerebrum/issues/19)) ([b31aab4](https://github.com/piurizza/cerebrum/commit/b31aab4c37800d7bcba2b1a4e8654a8ecd6eb30c))
* pick a note's location from a folder-tree modal instead of typing a path ([#9](https://github.com/piurizza/cerebrum/issues/9)) ([260dfd1](https://github.com/piurizza/cerebrum/commit/260dfd1fbbe11ccb78150c20f13e64ff21986ae7))
* publish prebuilt images and Linux desktop packages with each release ([610e0c8](https://github.com/piurizza/cerebrum/commit/610e0c8368ac0d043dcdf703a6213569de9ec2d6))
* read the daily-notes and templates folders from the server ([6bf8a4e](https://github.com/piurizza/cerebrum/commit/6bf8a4efdb1e8b12a1a69e66454d018d4ba04038))
* redesign app icon and favicon ([f19caae](https://github.com/piurizza/cerebrum/commit/f19caaea9ca81afae72b8f6e9ab6e03607c08ebe))
* save a note via Cmd/Ctrl+S ([#15](https://github.com/piurizza/cerebrum/issues/15)) ([17e0620](https://github.com/piurizza/cerebrum/commit/17e0620117b775f89e1a24fffe2a36a6db188441))
* scaffold Cerebrum (self-hosted markdown second brain) ([a4f9f13](https://github.com/piurizza/cerebrum/commit/a4f9f1315c9fd2bf94bb1474ec7d8d3a4c257c47))
* show a note's created/updated timestamps in the UI ([#11](https://github.com/piurizza/cerebrum/issues/11)) ([d4a7d2a](https://github.com/piurizza/cerebrum/commit/d4a7d2a8907953a9492de1ecf1f8136301936a1a))
* show the note's path above the editor, with a copy button ([2d4f96b](https://github.com/piurizza/cerebrum/commit/2d4f96b87f221fb762d3d6b86995f7338ecbabcd))
* show the vault offline when the server is unreachable ([6067b17](https://github.com/piurizza/cerebrum/commit/6067b17ccb21cf92f886f46f5688f96f92982b47))
* **watcher:** index out-of-band .md edits without a restart ([#18](https://github.com/piurizza/cerebrum/issues/18)) ([f89decd](https://github.com/piurizza/cerebrum/commit/f89decddb46328288ef8fbb76d8c22ddbf28d3f6))
* **watcher:** pair renames whose delete/create span separate batches (U3) ([9424f17](https://github.com/piurizza/cerebrum/commit/9424f171eae3a64fd258a6168720e38cd936fbd1))
* **watcher:** preserve links across single-step external renames ([#21](https://github.com/piurizza/cerebrum/issues/21)) ([664b751](https://github.com/piurizza/cerebrum/commit/664b751764193cdc6bb1a530300806b2780effd3))


### Bug Fixes

* close cross-window rename pairing and attachment-relocation gaps ([6511bfc](https://github.com/piurizza/cerebrum/commit/6511bfc680428879ee2dce0f4b2c210b766297d7))
* dark-mode text invisibility + general UI/UX pass ([3565c6f](https://github.com/piurizza/cerebrum/commit/3565c6f60c0edecd866c2b619217584ef4acd1ce))
* disambiguate notes with duplicate titles in the sidebar list ([dc252c4](https://github.com/piurizza/cerebrum/commit/dc252c49cd507d31f9b8a9b8db00a03e56675a5b))
* **frontend:** actually populate the offline vault cache after login ([c319b62](https://github.com/piurizza/cerebrum/commit/c319b62647fa5f695f599745368a32ae3f0cbb1b))
* **frontend:** keep preview images and long links inside the reading column ([bbd01c9](https://github.com/piurizza/cerebrum/commit/bbd01c983791d0b38310bd906bcee56e3e1b5598))
* **frontend:** two bugs found only by real end-to-end offline testing ([41be46f](https://github.com/piurizza/cerebrum/commit/41be46ff6fea6b9ada51b0bf50d914443f88feb5))
* **index:** close a real race and a missing prune/invalidate in the shared rename cache ([1a2bb84](https://github.com/piurizza/cerebrum/commit/1a2bb840294fde960f5d0184224f0410b02a4b93))
* **notes:** close file-write race conditions with per-path locking ([#22](https://github.com/piurizza/cerebrum/issues/22)) ([84e3cdb](https://github.com/piurizza/cerebrum/commit/84e3cdb28231316f1f446b4a6bf48429f31ea44c))
* **notes:** relocate attachment folder on retarget_note_links (U1) ([f73a5b6](https://github.com/piurizza/cerebrum/commit/f73a5b628ec674daea1c15cddd2bd5a06f3ee199))
* **review:** close logout-race and offline-guard closure-staleness bugs ([436b07a](https://github.com/piurizza/cerebrum/commit/436b07adb3279637413d51ac19da2898037f5d29))
* **review:** close offline-mode read-only, auth-boundary, and reliability gaps ([d3d2324](https://github.com/piurizza/cerebrum/commit/d3d2324581c55acb5a911fb25cf86bd51415df4b))
* **review:** pin generated-type aliases against wrong schema-key mapping ([8c786e7](https://github.com/piurizza/cerebrum/commit/8c786e7d67ab4a8699e13c97b099d524aec8c331))
