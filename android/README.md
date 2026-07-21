# Android

Native Kotlin app for Android 15 (`minSdk = targetSdk = compileSdk = 35`), sideload/internal install only. Uploads inbox SMS to the backend in `../backend/` via QR-provisioned device credentials and Tink HPKE-encrypted batches.

Full plan: the private agent repo's `projects/sms-ingest/docs/android-implementation-plan.md` (implementation structure, phases, tooling decisions) and `projects/sms-ingest/docs/sms-upload-app.md` (product scope). Those docs are not part of this public repo — see the root README for the public/private split.

## Status

Phase 1 (project scaffold) only: a buildable single-module Gradle project with a placeholder Compose screen. No permissions, QR scan, crypto, storage, networking, or SMS handling yet — those land in later phases.

## Stack

- Kotlin, Jetpack Compose (Material 3), single activity.
- Gradle version catalog (`gradle/libs.versions.toml`).
- Manual dependency wiring (`AppContainer`), no Hilt/Dagger.
- Planned for later phases: Room (local queue/dedupe state), Retrofit + OkHttp + kotlinx.serialization (network), Jetpack Security `EncryptedSharedPreferences` (credential storage), CameraX + ML Kit Barcode Scanning (QR), Tink (`tink-android`, batch encryption), WorkManager (background sync).

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
