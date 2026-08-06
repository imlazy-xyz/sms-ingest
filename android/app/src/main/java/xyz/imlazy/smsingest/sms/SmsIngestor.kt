package xyz.imlazy.smsingest.sms

import java.time.Instant
import java.util.UUID
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import xyz.imlazy.smsingest.crypto.DedupeId
import xyz.imlazy.smsingest.data.PendingBatchDao
import xyz.imlazy.smsingest.data.PendingBatchEntity
import xyz.imlazy.smsingest.data.UploadedDedupeDao
import xyz.imlazy.smsingest.setup.CredentialStore

/**
 * Turns platform-captured [SmsCapture]s into a queued [PendingBatchEntity].
 * The `sms/` package is documented as owning only platform reads
 * (`SmsBackfillReader`/`SmsReceiver`), but `PendingBatchEntity`'s own doc
 * comment and the Phase 6 plan both point [SmsRecord] at "feeding the batch
 * queue" — this class is that connection: the one place dedupe IDs get
 * computed for outbound messages (via [DedupeId]) and the one place
 * already-uploaded messages get filtered out locally, before ever touching
 * the network.
 *
 * A no-op (not a crash) if the device isn't provisioned yet:
 * `RECEIVE_SMS`/`READ_SMS` can be granted mid-setup, before the QR scan
 * stores [CredentialStore.getDeviceDedupeSecret] — an SMS captured during
 * that narrow window is dropped, not queued for later, since it cannot be
 * de-duplicated without the secret. Acceptable: real setup completes within
 * seconds of granting permissions.
 */
class SmsIngestor(
    private val pendingBatchDao: PendingBatchDao,
    private val uploadedDedupeDao: UploadedDedupeDao,
    private val credentialStore: CredentialStore,
) {
    private val json = Json

    suspend fun enqueue(captures: List<SmsCapture>) {
        if (captures.isEmpty()) return
        val dedupeSecret = credentialStore.getDeviceDedupeSecret() ?: return

        val records = captures.mapNotNull { capture ->
            val normalizedSender = DedupeId.normalizeSender(capture.sender)
            val dedupeId = DedupeId.compute(
                dedupeSecret = dedupeSecret,
                direction = SmsRecord.DIRECTION_INBOX,
                sender = normalizedSender,
                smsReceivedAtEpochMillis = capture.smsReceivedAtEpochMillis,
                body = capture.body,
            )
            if (uploadedDedupeDao.exists(dedupeId)) return@mapNotNull null

            SmsRecord(
                clientMessageId = UUID.randomUUID().toString(),
                dedupeId = dedupeId,
                direction = SmsRecord.DIRECTION_INBOX,
                sender = normalizedSender,
                body = capture.body,
                smsReceivedAt = Instant.ofEpochMilli(capture.smsReceivedAtEpochMillis).toString(),
                threadHint = capture.threadHint,
                simInfo = capture.simInfo,
            )
        }
        if (records.isEmpty()) return

        // Split into size-bounded batches so no single `pending_batches` row's
        // `messagesJson` can approach Android's ~2MB per-row CursorWindow limit
        // — a full historical backfill in one row previously threw
        // `SQLiteBlobTooBigException` the moment `getByState` tried to read it
        // back for upload (see PendingBatchDao.deleteOversized). Bounding by
        // encoded bytes, not message count, keeps the guarantee even for long
        // concatenated-SMS bodies.
        for (chunk in chunkBySize(records)) {
            val now = System.currentTimeMillis()
            pendingBatchDao.insert(
                PendingBatchEntity(
                    clientBatchId = UUID.randomUUID().toString(),
                    messagesJson = json.encodeToString(chunk),
                    state = PendingBatchEntity.STATE_PENDING,
                    createdAtEpochMillis = now,
                    updatedAtEpochMillis = now,
                ),
            )
        }
    }

    /**
     * Greedily packs [records] into chunks whose serialized size stays under
     * [MAX_BATCH_BYTES]. A single record larger than the cap still gets its own
     * chunk (an SMS record can't realistically approach the CursorWindow limit,
     * but the loop must always make progress).
     */
    private fun chunkBySize(records: List<SmsRecord>): List<List<SmsRecord>> {
        val chunks = mutableListOf<List<SmsRecord>>()
        var current = mutableListOf<SmsRecord>()
        var currentBytes = 0
        for (record in records) {
            val recordBytes = json.encodeToString(record).encodeToByteArray().size
            if (current.isNotEmpty() && currentBytes + recordBytes > MAX_BATCH_BYTES) {
                chunks += current
                current = mutableListOf()
                currentBytes = 0
            }
            current += record
            currentBytes += recordBytes
        }
        if (current.isNotEmpty()) chunks += current
        return chunks
    }

    companion object {
        /**
         * Per-batch serialized-message budget. Comfortably under Android's
         * ~2MB CursorWindow per-row limit even after JSON list framing and
         * multi-byte bodies, and small enough to keep each upload request modest.
         */
        const val MAX_BATCH_BYTES = 256 * 1024
    }
}
