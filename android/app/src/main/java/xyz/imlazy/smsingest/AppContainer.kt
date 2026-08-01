package xyz.imlazy.smsingest

import android.content.Context
import xyz.imlazy.smsingest.crypto.CryptoConfig
import xyz.imlazy.smsingest.crypto.DefaultKeysetVerifier
import xyz.imlazy.smsingest.crypto.KeysetVerifier
import xyz.imlazy.smsingest.data.AppDatabase
import xyz.imlazy.smsingest.network.IngestApi
import xyz.imlazy.smsingest.network.createIngestApi
import xyz.imlazy.smsingest.setup.CredentialStore
import xyz.imlazy.smsingest.setup.EncryptedCredentialStore
import xyz.imlazy.smsingest.sms.SmsIngestor
import xyz.imlazy.smsingest.sync.AndroidDeviceInfoProvider
import xyz.imlazy.smsingest.sync.DeviceInfoProvider
import xyz.imlazy.smsingest.sync.SyncScheduler

/**
 * Hand-wired dependency container (no Hilt/Dagger — see
 * projects/sms-ingest/docs/android-implementation-plan.md § Implementation-Detail Decisions).
 * Grows one property per dependency as later phases add the network client
 * and the crypto/dedupe helpers.
 */
class AppContainer(private val appContext: Context) {

    init {
        // Tink requires hybrid primitives be registered once before any
        // encrypt/decrypt or keyset-pin operation.
        CryptoConfig.ensureRegistered()
    }

    val credentialStore: CredentialStore by lazy { EncryptedCredentialStore(appContext) }

    val database: AppDatabase by lazy { AppDatabase.build(appContext) }

    val keysetVerifier: KeysetVerifier by lazy { DefaultKeysetVerifier() }

    val deviceInfoProvider: DeviceInfoProvider by lazy { AndroidDeviceInfoProvider(appContext) }

    val syncScheduler: SyncScheduler by lazy { SyncScheduler(appContext) }

    /** Consumed by [xyz.imlazy.smsingest.sms.SmsReceiver], which is manifest-registered and live. */
    val smsIngestor: SmsIngestor by lazy {
        SmsIngestor(database.pendingBatchDao(), database.uploadedDedupeDao(), credentialStore)
    }

    /**
     * Built fresh on every call (not `by lazy`) since [CredentialStore.getApiBaseUrl]
     * is unset before setup completes — caching a `null` result from an early
     * call would wrongly stick even after provisioning finishes. Cheap: just
     * a Retrofit/OkHttp client construction, called at most once per
     * [xyz.imlazy.smsingest.sync.SyncWorker] run.
     */
    fun createIngestApiOrNull(): IngestApi? =
        credentialStore.getApiBaseUrl()?.let { baseUrl ->
            createIngestApi(baseUrl) { credentialStore.getDeviceToken() }
        }
}
