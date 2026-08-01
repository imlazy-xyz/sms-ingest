# Android

Native Kotlin app for Android 15 (`minSdk = targetSdk = compileSdk = 35`), sideload/internal install only. Uploads inbox SMS to the backend in `../backend/` via QR-provisioned device credentials and Tink HPKE-encrypted batches.

Full plan: the private agent repo's `projects/sms-ingest/docs/android-implementation-plan.md` (implementation structure, phases, tooling decisions) and `projects/sms-ingest/docs/sms-upload-app.md` (product scope). Those docs are not part of this public repo — see the root README for the public/private split.

## Status

Phases 1–7 of `docs/android-implementation-plan.md` are implemented: scaffold, setup/QR provisioning (`setup/`), Room local storage (`data/`), Tink HPKE crypto (`crypto/`), a Retrofit network client (`network/`), SMS capture (`sms/`), and background sync/retry (`sync/`).

- **Setup/provisioning**: permission-consent screen, CameraX + ML Kit QR scan, QR payload parsing/validation (`setup/ProvisioningPayload.kt`), and encrypted on-device credential storage (`setup/CredentialStore.kt`). `server_key_pin` is fetched-and-verified against the backend's real public keyset via `GET /v1/public-key` (`crypto/KeysetVerifier.kt`) before setup completes.
- **Local storage**: Room `AppDatabase` (`data/`) with a `pending_batches` outbound queue (keyed by `client_batch_id`) and an `uploaded_dedupe_ids` table for offline duplicate suppression, plus `crypto/DedupeId.kt` computing the HMAC dedupe fingerprint — canonicalization matches the backend's `backend/app/core/dedupe.py` byte-for-byte.
- **Crypto**: `crypto/BatchEncryptor.kt` (Tink HPKE hybrid encrypt) and `crypto/ContextInfo.kt` (canonical `context_info` bytes bound into the ciphertext, matching `backend/app/core/crypto.py` byte-for-byte — cross-checked against a real backend-generated fixture in `crypto/CryptoInteropTest.kt`).
- **Network**: Retrofit `IngestApi` (`network/IngestApi.kt`) for `POST /v1/uploads/sms-batches`, with an `AuthInterceptor` attaching the bearer token and never logging it.
- **SMS capture**: `sms/SmsBackfillReader.kt` (historical inbox read) and `sms/SmsReceiver.kt` (new inbox SMS), both feeding `sms/SmsIngestor.kt`, which computes dedupe ids and queues a `PendingBatchEntity`.
- **Sync and retry**: `sync/SyncWorker.kt` (WorkManager) reads pending batches, encrypts and uploads each via `sync/BatchSyncer.kt`, and records accepted/duplicate message dedupe ids on success. `sync/SyncScheduler.kt` schedules a periodic reconciliation sync (any-network, exponential backoff), an expedited one-time sync triggered from `SmsReceiver` after a new SMS, and a one-time historical backfill (`sync/BackfillWorker.kt`) enqueued once setup completes.

Packaging/signing for a sideload release (Phase 9) has not started.

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

Signing/packaging instructions land in Phase 9 of the implementation plan, once there's a release worth installing.
