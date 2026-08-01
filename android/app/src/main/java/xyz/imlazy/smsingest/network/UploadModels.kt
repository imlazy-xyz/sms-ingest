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

private const val FIELD_API_BASE_URL = "api_base_url"
private const val FIELD_PAYLOAD_TYPE = "payload_type"
private const val FIELD_VERSION = "version"
private const val FIELD_CLIENT_BATCH_ID = "client_batch_id"

/**
 * The one `context_info` shape this app ever sends. This is the shared
 * source of truth for both halves of the HPKE context-binding contract: the
 * wire `context_info` object in the request body, and the fields
 * [xyz.imlazy.smsingest.crypto.ContextInfo.canonicalBytes] binds into the
 * ciphertext ([toContextFields]). Building both from one instance is what
 * keeps them from drifting apart — the backend re-derives its own canonical
 * bytes from the request body's `context_info`, so any mismatch (missing
 * field, different value, different field name) breaks decryption silently
 * rather than with a clear error (`xyz.imlazy.smsingest.sync.BatchSyncer`
 * is the only caller that constructs this and must keep using
 * [toContextFields], never a hand-built map, for the HPKE call).
 *
 * [payloadType] has no default value on purpose: `kotlinx.serialization`
 * omits default-valued properties from encoded JSON unless `encodeDefaults`
 * is turned on, which would silently drop this field from the request body
 * whenever it equals its default — exactly the kind of missing-field
 * mismatch this class exists to prevent. Callers always pass
 * [PAYLOAD_TYPE_SMS_BATCH] explicitly.
 */
@Serializable
data class UploadContextInfo(
    @SerialName(FIELD_API_BASE_URL) val apiBaseUrl: String,
    @SerialName(FIELD_PAYLOAD_TYPE) val payloadType: String,
    @SerialName(FIELD_VERSION) val version: Int,
    @SerialName(FIELD_CLIENT_BATCH_ID) val clientBatchId: String,
) {

    /** The exact fields to pass to [xyz.imlazy.smsingest.crypto.ContextInfo.canonicalBytes] for this instance. */
    fun toContextFields(): Map<String, Any> = mapOf(
        FIELD_API_BASE_URL to apiBaseUrl,
        FIELD_PAYLOAD_TYPE to payloadType,
        FIELD_VERSION to version,
        FIELD_CLIENT_BATCH_ID to clientBatchId,
    )

    companion object {
        const val PAYLOAD_TYPE_SMS_BATCH = "sms_batch"
    }
}

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
