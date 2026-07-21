package xyz.imlazy.smsingest

import android.content.Context

/**
 * Hand-wired dependency container (no Hilt/Dagger — see
 * projects/sms-ingest/docs/android-implementation-plan.md § Implementation-Detail Decisions).
 * Grows one property per dependency as later phases add credential storage,
 * the Room database, the network client, and the crypto/dedupe helpers.
 */
class AppContainer(private val appContext: Context)
