package xyz.imlazy.smsingest

import android.content.Context
import xyz.imlazy.smsingest.data.AppDatabase
import xyz.imlazy.smsingest.setup.CredentialStore
import xyz.imlazy.smsingest.setup.EncryptedCredentialStore

/**
 * Hand-wired dependency container (no Hilt/Dagger — see
 * projects/sms-ingest/docs/android-implementation-plan.md § Implementation-Detail Decisions).
 * Grows one property per dependency as later phases add the network client
 * and the crypto/dedupe helpers.
 */
class AppContainer(private val appContext: Context) {

    val credentialStore: CredentialStore by lazy { EncryptedCredentialStore(appContext) }

    val database: AppDatabase by lazy { AppDatabase.build(appContext) }
}
