package xyz.imlazy.smsingest.setup

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Persists the QR-provisioned device credentials and the pin-verified backend
 * public keyset (projects/sms-ingest/docs/android-implementation-plan.md §
 * Implementation-Detail Decisions: Jetpack Security `EncryptedSharedPreferences`,
 * never Room/logs/backups). An interface so [SetupViewModel] can be
 * unit-tested without the Android Keystore.
 */
interface CredentialStore {
    fun isProvisioned(): Boolean
    fun save(payload: ProvisioningPayload, publicKeysetJson: String)

    fun getApiBaseUrl(): String?
    fun getServerKeyId(): String?
    fun getServerKeyPin(): String?
    fun getPublicKeysetJson(): String?
}

class EncryptedCredentialStore(context: Context) : CredentialStore {

    private val appContext = context.applicationContext

    private val prefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            PREFS_FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    override fun isProvisioned(): Boolean = prefs.contains(KEY_DEVICE_ID)

    override fun getApiBaseUrl(): String? = prefs.getString(KEY_API_BASE_URL, null)

    override fun getServerKeyId(): String? = prefs.getString(KEY_SERVER_KEY_ID, null)

    override fun getServerKeyPin(): String? = prefs.getString(KEY_SERVER_KEY_PIN, null)

    override fun getPublicKeysetJson(): String? = prefs.getString(KEY_PUBLIC_KEYSET_JSON, null)

    override fun save(payload: ProvisioningPayload, publicKeysetJson: String) {
        prefs.edit()
            .putString(KEY_DEVICE_ID, payload.deviceId)
            .putString(KEY_DEVICE_TOKEN, payload.deviceToken)
            .putString(KEY_DEVICE_DEDUPE_SECRET, payload.deviceDedupeSecret)
            .putString(KEY_API_BASE_URL, payload.apiBaseUrl)
            .putString(KEY_SERVER_KEY_ID, payload.serverKeyId)
            .putString(KEY_SERVER_KEY_PIN, payload.serverKeyPin)
            .putString(KEY_PUBLIC_KEYSET_JSON, publicKeysetJson)
            .apply()
    }

    private companion object {
        const val PREFS_FILE_NAME = "device_credentials"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_DEVICE_TOKEN = "device_token"
        const val KEY_DEVICE_DEDUPE_SECRET = "device_dedupe_secret"
        const val KEY_API_BASE_URL = "api_base_url"
        const val KEY_SERVER_KEY_ID = "server_key_id"
        const val KEY_SERVER_KEY_PIN = "server_key_pin"
        const val KEY_PUBLIC_KEYSET_JSON = "public_keyset_json"
    }
}
