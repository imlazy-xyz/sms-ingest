package xyz.imlazy.smsingest.sms

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * A single SMS as read from the platform, before a dedupe ID or client
 * message ID is assigned. [SmsBackfillReader] and [SmsReceiver] both
 * canonicalize into this shape (per
 * `projects/sms-ingest/docs/android-implementation-plan.md` Phase 6) so
 * [SmsIngestor] has one input type regardless of source.
 *
 * [sender] should already be normalized
 * ([xyz.imlazy.smsingest.crypto.DedupeId.normalizeSender]) by the caller so
 * the value fed into the dedupe HMAC and the value eventually stored/sent
 * are identical — [SmsIngestor] does this normalization, not the readers.
 */
data class SmsCapture(
    val sender: String,
    val body: String,
    val smsReceivedAtEpochMillis: Long,
    val threadHint: String? = null,
    val simInfo: String? = null,
)

/**
 * Wire shape of one message inside the plaintext batch body, per
 * `projects/sms-ingest/docs/backend-plan.md` § Upload API. Field names must
 * match the backend's `messages[]` entries exactly
 * (`backend/app/services/ingestion.py::_validate_message`). Never sent as
 * standalone JSON — a `List<SmsRecord>` is what `PendingBatchEntity
 * .messagesJson` stores, and the full plaintext envelope (adding
 * `schema_version`/`device`, see `sync.BatchPayload`) gets assembled around
 * it at encrypt/upload time (`sync.BatchSyncer`), then HPKE-encrypted into
 * `network.UploadBatchRequest.ciphertext`.
 *
 * [direction] has no default value on purpose, same reasoning as
 * `network/UploadModels.kt`'s `UploadContextInfo.payloadType`:
 * `kotlinx.serialization` omits default-valued properties from encoded JSON
 * unless `encodeDefaults` is set, and the backend rejects a message with
 * `direction` missing/not `"inbox"` (`_validate_message`: `invalid_direction`)
 * — a silently-dropped default here would mean every queued message gets
 * rejected. v1 is inbox-only (see `open-questions.md` "Decide whether to
 * support sent SMS"), so every caller passes [DIRECTION_INBOX] explicitly.
 */
@Serializable
data class SmsRecord(
    @SerialName("client_message_id") val clientMessageId: String,
    @SerialName("dedupe_id") val dedupeId: String,
    val direction: String,
    val sender: String,
    val body: String,
    @SerialName("sms_received_at") val smsReceivedAt: String,
    @SerialName("thread_hint") val threadHint: String? = null,
    @SerialName("sim_info") val simInfo: String? = null,
) {
    companion object {
        const val DIRECTION_INBOX = "inbox"
    }
}
