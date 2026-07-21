# Android

Native Kotlin app for Android 15 (`minSdk = targetSdk = compileSdk = 35`), sideload/internal install only. Uploads inbox SMS to the backend in `../backend/` via QR-provisioned device credentials and Tink HPKE-encrypted batches.

Full plan: the private agent repo's `projects/sms-ingest/docs/android-implementation-plan.md` (implementation structure, phases, tooling decisions) and `projects/sms-ingest/docs/sms-upload-app.md` (product scope). Those docs are not part of this public repo — see the root README for the public/private split.

## Status

Phase 2 (setup/permissions/QR provisioning) landed on top of Phase 1's scaffold: a permission-consent screen, a CameraX + ML Kit QR scan screen, QR payload parsing/validation (`setup/ProvisioningPayload.kt`), and encrypted on-device credential storage (`setup/CredentialStore.kt`). `server_key_pin` is validated for shape and stored, but not yet compared against the backend's actual public keyset — the QR only carries the pin (a fingerprint), not the keyset itself, and no endpoint currently serves it; see the private agent repo's `open-questions.md` for that gap, which Phase 4/5 (crypto/network) must resolve.

Phase 3 (local storage) adds a Room `AppDatabase` (`data/`) with a `pending_batches` table (outbound batch queue state keyed by `client_batch_id`, message payload stored as JSON pending the `SmsRecord` shape Phase 6 defines) and an `uploaded_dedupe_ids` table (offline duplicate suppression before hitting the network), plus `crypto/DedupeId.kt` computing the HMAC dedupe fingerprint — canonicalization matches the backend's `backend/app/core/dedupe.py` byte-for-byte, unit-tested against a cross-checked known-answer vector. No crypto (batch encryption), networking, or SMS handling yet — those land in later phases.

## Stack

- Kotlin, Jetpack Compose (Material 3), single activity.
- Gradle version catalog (`gradle/libs.versions.toml`).
- Manual dependency wiring (`AppContainer`), no Hilt/Dagger.
- kotlinx.serialization (QR payload parsing), Jetpack Security `EncryptedSharedPreferences` (credential storage), CameraX + ML Kit Barcode Scanning (QR), Room + KSP (local batch queue / dedupe cache).
- Planned for later phases: Retrofit + OkHttp (network), Tink (`tink-android`, batch encryption), WorkManager (background sync).

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
