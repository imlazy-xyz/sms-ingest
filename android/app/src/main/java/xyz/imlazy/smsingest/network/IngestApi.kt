package xyz.imlazy.smsingest.network

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.POST

/**
 * Wire contract for `POST /v1/uploads/sms-batches`, per
 * `projects/sms-ingest/docs/backend-plan.md` § Upload API. The path has no
 * leading slash so it appends onto (rather than overrides) the base URL's
 * path — see [createIngestApi], which enforces a trailing-slash base URL.
 *
 * Retrofit throws [retrofit2.HttpException] on a non-2xx response, including
 * 401 (bad/expired/revoked token) and 400 (batch rejected — see
 * `backend/app/api/uploads.py`). Interpreting the status code is the sync/
 * retry caller's job (added later); this interface does not catch or
 * classify it.
 */
interface IngestApi {
    @POST("v1/uploads/sms-batches")
    suspend fun uploadBatch(@Body request: UploadBatchRequest): UploadResponse
}

/**
 * Builds an [IngestApi] against [baseUrl] (the QR-provisioned
 * `api_base_url`, with or without a trailing slash) whose [OkHttpClient]
 * attaches the bearer token from [deviceToken] via [AuthInterceptor] and
 * carries no logging interceptor.
 */
fun createIngestApi(baseUrl: String, deviceToken: () -> String?): IngestApi {
    val client = OkHttpClient.Builder()
        .addInterceptor(AuthInterceptor(deviceToken))
        // Default 10s is too tight for a Cloud Run cold start (min-instances=0)
        // combined with a large chunked batch (up to ~700 messages / 256K chars,
        // MAX_BATCH_BYTES) taking a while to decrypt + insert server-side.
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
    val json = Json { ignoreUnknownKeys = true }
    return Retrofit.Builder()
        .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
        .client(client)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(IngestApi::class.java)
}
