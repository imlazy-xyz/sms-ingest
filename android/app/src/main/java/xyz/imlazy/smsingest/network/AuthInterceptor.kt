package xyz.imlazy.smsingest.network

import java.io.IOException
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Attaches `Authorization: Bearer <device_token>` to every request. No
 * logging interceptor is installed on this client (see
 * `projects/sms-ingest/docs/android-implementation-plan.md` Phase 5) — do not
 * add one without an explicit header-redacting wrapper, since the raw token
 * must never be logged.
 *
 * [deviceToken] is read on every request rather than captured once at
 * construction, so a token rotation mid-session (or a token becoming
 * available after provisioning) takes effect on the next call without
 * rebuilding the [okhttp3.OkHttpClient].
 */
class AuthInterceptor(private val deviceToken: () -> String?) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val token = deviceToken()
            ?: throw IOException("AuthInterceptor invoked with no device token stored")
        val request = chain.request().newBuilder()
            .addHeader("Authorization", "Bearer $token")
            .build()
        return chain.proceed(request)
    }
}
