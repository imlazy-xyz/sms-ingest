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

        val now = System.currentTimeMillis()
        pendingBatchDao.insert(
            PendingBatchEntity(
                clientBatchId = UUID.randomUUID().toString(),
                messagesJson = json.encodeToString(records),
                state = PendingBatchEntity.STATE_PENDING,
                createdAtEpochMillis = now,
                updatedAtEpochMillis = now,
            ),
        )
    }
}
