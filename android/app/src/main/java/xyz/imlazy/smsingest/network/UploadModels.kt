package xyz.imlazy.smsingest.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Wire shapes of `POST /v1/uploads/sms-batches`, per
 * `projects/sms-ingest/docs/backend-plan.md` § Upload API. Field names and
 * nesting must match `backend/app/models/api.py` exactly.
 */
@Serializable
data class EncryptionMeta(
    val scheme: String,
    @SerialName("server_key_id") val serverKeyId: String,
    @SerialName("server_key_pin") val serverKeyPin: String,
)

/**
 * The one `context_info` shape this app ever sends. Values here must stay in
 * sync with whatever [xyz.imlazy.smsingest.crypto.ContextInfo.canonicalBytes]
 * fields the caller used to bind the HPKE ciphertext — the backend
 * re-derives its own canonical bytes from this JSON object, so a mismatch
 * (missing field, different value) breaks decryption, not just this request.
 *
 * [payloadType] has no default value on purpose: `kotlinx.serialization`
 * omits default-valued properties from encoded JSON unless `encodeDefaults`
 * is turned on, which would silently drop this field from the request body
 * whenever it equals its default — exactly the kind of missing-field
 * mismatch this class exists to prevent. Callers always pass `"sms_batch"`
 * explicitly.
 */
@Serializable
data class UploadContextInfo(
    @SerialName("api_base_url") val apiBaseUrl: String,
    @SerialName("payload_type") val payloadType: String,
    val version: Int,
    @SerialName("client_batch_id") val clientBatchId: String,
)

@Serializable
data class UploadBatchRequest(
    val version: Int,
    @SerialName("device_time") val deviceTime: String,
    @SerialName("client_batch_id") val clientBatchId: String,
    val encryption: EncryptionMeta,
    val ciphertext: String,
    @SerialName("context_info") val contextInfo: UploadContextInfo,
)

@Serializable
data class RejectedItem(
    @SerialName("client_message_id") val clientMessageId: String,
    val reason: String,
)

@Serializable
data class NextSync(
    @SerialName("retry_after_seconds") val retryAfterSeconds: Int? = null,
)

/** `status` is `"accepted"` or `"partial"` — see `backend/app/models/api.py::UploadResponse`. */
@Serializable
data class UploadResponse(
    val status: String,
    @SerialName("server_batch_id") val serverBatchId: String,
    @SerialName("accepted_count") val acceptedCount: Int,
    @SerialName("duplicate_count") val duplicateCount: Int,
    @SerialName("rejected_count") val rejectedCount: Int,
    val rejected: List<RejectedItem> = emptyList(),
    @SerialName("next_sync") val nextSync: NextSync = NextSync(),
)
