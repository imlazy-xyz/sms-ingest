package xyz.imlazy.smsingest.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/** Outbound batch queue state, keyed by the client-generated batch id. */
@Entity(tableName = "pending_batches")
data class PendingBatchEntity(
    @PrimaryKey val clientBatchId: String,
    /** JSON-encoded list of queued messages; the message shape lives in `sms/SmsRecord.kt` (Phase 6). */
    val messagesJson: String,
    val state: String,
    val createdAtEpochMillis: Long,
    val updatedAtEpochMillis: Long,
    val retryCount: Int = 0,
    val lastError: String? = null,
) {
    companion object {
        const val STATE_PENDING = "pending"
        const val STATE_SENT = "sent"
    }
}
