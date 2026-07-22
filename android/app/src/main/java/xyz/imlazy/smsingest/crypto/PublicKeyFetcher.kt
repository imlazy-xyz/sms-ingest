package xyz.imlazy.smsingest.crypto

import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Wire shape of `GET /v1/public-key`, per
 * `projects/sms-ingest/docs/backend-plan.md` § Upload API. Field names must
 * match `backend/app/api/routes` exactly. Only the response envelope is parsed
 * here; the security-critical `context_info` canonicalization is handled by
 * [ContextInfo], not by this serializer.
 */
@Serializable
data class PublicKeyResponse(
    val scheme: String,
    @SerialName("server_key_id") val serverKeyId: String,
    @SerialName("server_key_pin") val serverKeyPin: String,
    @SerialName("public_keyset_json") val publicKeysetJson: String,
)

/**
 * Unauthenticated fetch of the backend's public keyset. Deliberately a plain
 * `HttpURLConnection` GET rather than a full HTTP client — Retrofit/OkHttp is
 * Phase 5's `IngestApi` scope and adding it for this one call would be
 * premature. Never log the response body (it carries keyset material).
 */
class PublicKeyFetcher(
    private val json: Json = Json { ignoreUnknownKeys = true },
) {

    /** GET `{apiBaseUrl}/v1/public-key`; throws on transport/parse failure (caller wraps). */
    suspend fun fetch(apiBaseUrl: String): PublicKeyResponse = withContext(Dispatchers.IO) {
        val url = URL(apiBaseUrl.trimEnd('/') + PATH)
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = TIMEOUT_MILLIS
            readTimeout = TIMEOUT_MILLIS
            setRequestProperty("Accept", "application/json")
        }
        try {
            val status = connection.responseCode
            if (status != HttpURLConnection.HTTP_OK) {
                throw IllegalStateException("public-key request failed: HTTP $status")
            }
            val body = connection.inputStream.bufferedReader().use { it.readText() }
            json.decodeFromString<PublicKeyResponse>(body)
        } finally {
            connection.disconnect()
        }
    }

    private companion object {
        const val PATH = "/v1/public-key"
        const val TIMEOUT_MILLIS = 15_000
    }
}
