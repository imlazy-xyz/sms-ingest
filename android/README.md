# Android

Native Kotlin app for Android 15 (`minSdk = targetSdk = compileSdk = 35`), sideload/internal install only. Uploads inbox SMS to the backend in `../backend/` via QR-provisioned device credentials and Tink HPKE-encrypted batches.

Full plan: the private agent repo's `projects/sms-ingest/docs/android-implementation-plan.md` (implementation structure, phases, tooling decisions) and `projects/sms-ingest/docs/sms-upload-app.md` (product scope). Those docs are not part of this public repo — see the root README for the public/private split.

## Status

Phases 1–8 of `docs/android-implementation-plan.md` are implemented: scaffold, setup/QR provisioning (`setup/`), Room local storage (`data/`), Tink HPKE crypto (`crypto/`), a Retrofit network client (`network/`), SMS capture (`sms/`), background sync/retry (`sync/`), and unit-test coverage of all of the above.

- **Setup/provisioning**: permission-consent screen, CameraX + ML Kit QR scan, QR payload parsing/validation (`setup/ProvisioningPayload.kt`), and encrypted on-device credential storage (`setup/CredentialStore.kt`). `server_key_pin` is fetched-and-verified against the backend's real public keyset via `GET /v1/public-key` (`crypto/KeysetVerifier.kt`) before setup completes.
- **Local storage**: Room `AppDatabase` (`data/`) with a `pending_batches` outbound queue (keyed by `client_batch_id`) and an `uploaded_dedupe_ids` table for offline duplicate suppression, plus `crypto/DedupeId.kt` computing the HMAC dedupe fingerprint — canonicalization matches the backend's `backend/app/core/dedupe.py` byte-for-byte.
- **Crypto**: `crypto/BatchEncryptor.kt` (Tink HPKE hybrid encrypt) and `crypto/ContextInfo.kt` (canonical `context_info` bytes bound into the ciphertext, matching `backend/app/core/crypto.py` byte-for-byte — cross-checked against a real backend-generated fixture in `crypto/CryptoInteropTest.kt`).
- **Network**: Retrofit `IngestApi` (`network/IngestApi.kt`) for `POST /v1/uploads/sms-batches`, with an `AuthInterceptor` attaching the bearer token and never logging it.
- **SMS capture**: `sms/SmsBackfillReader.kt` (historical inbox read) and `sms/SmsReceiver.kt` (new inbox SMS), both feeding `sms/SmsIngestor.kt`, which computes dedupe ids and queues a `PendingBatchEntity`.
- **Sync and retry**: `sync/SyncWorker.kt` (WorkManager) reads pending batches, encrypts and uploads each via `sync/BatchSyncer.kt`, and records accepted/duplicate message dedupe ids on success. `sync/SyncScheduler.kt` schedules a periodic reconciliation sync (any-network, exponential backoff), an expedited one-time sync triggered from `SmsReceiver` after a new SMS, and a one-time historical backfill (`sync/BackfillWorker.kt`) enqueued once setup completes.

Phase 9 (packaging/release) is in progress — see Install (sideload) below. Instrumented tests (`androidTest`: permission flow, Room DAO behavior, WorkManager scheduling) remain undone; `.github/workflows/android-ci.yml` has no emulator step, so this needs an explicit tooling decision before any `androidTest` code gets real verification.

## Stack

- Kotlin, Jetpack Compose (Material 3), single activity.
- Gradle version catalog (`gradle/libs.versions.toml`).
- Manual dependency wiring (`AppContainer`), no Hilt/Dagger.
- kotlinx.serialization (QR payload parsing, wire models), Jetpack Security `EncryptedSharedPreferences` (credential storage), CameraX + ML Kit Barcode Scanning (QR), Room + KSP (local batch queue / dedupe cache), Tink (`tink-android`, batch encryption), Retrofit + OkHttp (network client), WorkManager (background sync/retry).

## Build

Requires network access to Google's/Maven Central's Gradle plugin and dependency repositories (no Android SDK/emulator needed just to compile). Kotlin compiles against a JDK 17 toolchain (`kotlin { jvmToolchain(17) }` in `app/build.gradle.kts`) — Gradle auto-downloads one via the Foojay resolver plugin if a matching JDK isn't already installed, so you don't need JDK 17 specifically on `PATH`.

```sh
cd android
./gradlew assembleDebug
./gradlew testDebugUnitTest
```

This has not been build-verified in the agent sandbox, which has no JDK/Android SDK installed (see `projects/sms-ingest/docs/android-implementation-plan.md` § Sandbox Constraint). `.github/workflows/android-ci.yml` runs `assembleDebug` and `testDebugUnitTest` on every push/PR touching `android/**` — check that workflow's status before relying on a change that hasn't been verified locally.

## Install (sideload)

There is no Play signing key — this is a sideload-only app, so you sign a release build yourself with a self-managed keystore that never enters this repo (`android/keystore.properties` and any `.jks`/`.keystore` file are gitignored).

1. From inside `android/`, generate a release keystore once (keep it outside version control, back it up somewhere durable — losing it means future updates can't be installed over an existing app copy without uninstalling first):

   ```sh
   cd android
   keytool -genkeypair -v \
     -keystore release.jks \
     -alias sms-ingest-release \
     -keyalg RSA -keysize 2048 -validity 10000
   ```

2. Copy `android/keystore.properties.example` to `android/keystore.properties` and fill in the `storeFile` path (relative to `android/`), the store/key passwords you chose, and the key alias.
3. Build and install the signed release APK:

   ```sh
   cd android
   ./gradlew assembleRelease
   adb install app/build/outputs/apk/release/app-release.apk
   ```

If `android/keystore.properties` is absent, `assembleRelease` still runs but produces an unsigned APK that `adb install` will reject — this is expected for CI's push/PR workflow (which only builds/tests debug) and is not an error to work around there.

### No local build environment? Build the signed APK in CI instead

`.github/workflows/android-release.yml` (manual trigger only, `workflow_dispatch`) builds a signed release APK using repo secrets (`RELEASE_KEYSTORE_BASE64`, `RELEASE_KEYSTORE_PASSWORD`, `RELEASE_KEY_ALIAS`, `RELEASE_KEY_PASSWORD`) and uploads it as a downloadable artifact — no local JDK/Android SDK needed:

```sh
gh workflow run android-release.yml
gh run watch    # wait for it to finish
gh run download --name sms-ingest-release-apk
adb install app-release.apk
```

The keystore never leaves GitHub's encrypted secret storage or the ephemeral CI runner — it's decoded to a temp file, used to sign, then deleted before the job ends. This workflow is separate from `android-ci.yml` (which runs on every push/PR, including from forks) specifically so pull_request runs never have these secrets in scope.
