package xyz.imlazy.smsingest.sync

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import java.util.UUID

/** Populates the [DeviceInfo] block of the plaintext batch envelope. */
interface DeviceInfoProvider {
    fun current(): DeviceInfo
}

/**
 * Generates and persists a random per-install [DeviceInfo.appInstanceId] the
 * first time it's needed. Not sensitive — a bare correlation id, not a
 * credential — so plain `SharedPreferences` rather than
 * [xyz.imlazy.smsingest.setup.CredentialStore]'s encrypted store.
 */
class AndroidDeviceInfoProvider(context: Context) : DeviceInfoProvider {

    private val appContext = context.applicationContext

    private val prefs by lazy { appContext.getSharedPreferences(PREFS_FILE_NAME, Context.MODE_PRIVATE) }

    override fun current(): DeviceInfo = DeviceInfo(
        appInstanceId = appInstanceId(),
        androidSdk = Build.VERSION.SDK_INT,
        appVersion = appVersionName(),
    )

    private fun appInstanceId(): String {
        prefs.getString(KEY_APP_INSTANCE_ID, null)?.let { return it }
        val generated = UUID.randomUUID().toString()
        prefs.edit().putString(KEY_APP_INSTANCE_ID, generated).apply()
        return generated
    }

    private fun appVersionName(): String =
        try {
            appContext.packageManager.getPackageInfo(appContext.packageName, 0).versionName ?: "unknown"
        } catch (_: PackageManager.NameNotFoundException) {
            "unknown"
        }

    private companion object {
        const val PREFS_FILE_NAME = "device_info"
        const val KEY_APP_INSTANCE_ID = "app_instance_id"
    }
}
