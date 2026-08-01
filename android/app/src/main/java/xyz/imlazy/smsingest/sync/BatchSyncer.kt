package xyz.imlazy.smsingest.sync

import java.io.IOException
import java.time.Instant
import java.util.Base64
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import xyz.imlazy.smsingest.crypto.BatchEncryptor
import xyz.imlazy.smsingest.crypto.ContextInfo
import xyz.imlazy.smsingest.data.PendingBatchDao
import xyz.imlazy.smsingest.data.PendingBatchEntity
import xyz.imlazy.smsingest.data.UploadedDedupeDao
import xyz.imlazy.smsingest.data.UploadedDedupeIdEntity
import xyz.imlazy.smsingest.network.EncryptionMeta
import xyz.imlazy.smsingest.network.IngestApi
import xyz.imlazy.smsingest.network.UploadBatchRequest
import xyz.imlazy.smsingest.network.UploadContextInfo
import xyz.imlazy.smsingest.network.UploadResponse
import xyz.imlazy.smsingest.setup.CredentialStore
import xyz.imlazy.smsingest.sms.SmsRecord

/** Outcome of one [BatchSyncer.sync] pass; [SyncWorker] maps this to a WorkManager `Result`. */
enum class SyncResult { SUCCESS, RETRY, NOT_PROVISIONED }

/**
 * Uploads queued [PendingBatchEntity] rows: encrypts each with
 * [BatchEncryptor] bound to the exact [UploadContextInfo] sent as the
 * request's `context_info` (via [UploadContextInfo.toContextFields] — the
 * single source of truth that keeps the HPKE-bound context and the wire
 * `context_info` object from diverging), uploads via [IngestApi], and
 * records each accepted/duplicate message's dedupe id in [UploadedDedupeDao]
 * on success. A per-batch send that fails (network error or non-2xx
 * response) leaves the batch `pending` with `retryCount`/`lastError` updated,
 * for [SyncWorker]'s WorkManager-managed exponential backoff to retry.
 *
 * Kept free of `android.*`/WorkManager types so it is unit-testable with
 * fakes; [SyncWorker] is the thin WorkManager adapter around this class, the
 * same split used elsewhere in this codebase
 * ([xyz.imlazy.smsingest.sms.SmsIngestor] vs. `SmsReceiver`,
 * [xyz.imlazy.smsingest.crypto.KeysetVerifier] vs. `SetupViewModel`).
 */
class BatchSyncer(
    private val pendingBatchDao: PendingBatchDao,
    private val uploadedDedupeDao: UploadedDedupeDao,
    private val credentialStore: CredentialStore,
    private val ingestApiProvider: () -> IngestApi?,
    private val deviceInfoProvider: DeviceInfoProvider,
) {
    private val json = Json

    suspend fun sync(): SyncResult {
        val apiBaseUrl = credentialStore.getApiBaseUrl()
        val serverKeyId = credentialStore.getServerKeyId()
        val serverKeyPin = credentialStore.getServerKeyPin()
        val publicKeysetJson = credentialStore.getPublicKeysetJson()
        val ingestApi = ingestApiProvider()
        if (apiBaseUrl == null || serverKeyId == null || serverKeyPin == null ||
            publicKeysetJson == null || ingestApi == null
        ) {
            return SyncResult.NOT_PROVISIONED
        }

        val pending = pendingBatchDao.getByState(PendingBatchEntity.STATE_PENDING)
        if (pending.isEmpty()) return SyncResult.SUCCESS

        val encryptor = BatchEncryptor.fromPublicKeysetJson(publicKeysetJson)
        var anyFailed = false
        for (batch in pending) {
            val succeeded = uploadOne(batch, apiBaseUrl, serverKeyId, serverKeyPin, encryptor, ingestApi)
            if (!succeeded) anyFailed = true
        }
        return if (anyFailed) SyncResult.RETRY else SyncResult.SUCCESS
    }

    private suspend fun uploadOne(
        batch: PendingBatchEntity,
        apiBaseUrl: String,
        serverKeyId: String,
        serverKeyPin: String,
        encryptor: BatchEncryptor,
        ingestApi: IngestApi,
    ): Boolean {
        val messages = json.decodeFromString<List<SmsRecord>>(batch.messagesJson)
        val contextInfo = UploadContextInfo(
            apiBaseUrl = apiBaseUrl,
            payloadType = UploadContextInfo.PAYLOAD_TYPE_SMS_BATCH,
            version = PROTOCOL_VERSION,
            clientBatchId = batch.clientBatchId,
        )
        val plaintext = json.encodeToString(
            BatchPayload(
                schemaVersion = BatchPayload.SCHEMA_VERSION,
                device = deviceInfoProvider.current(),
                messages = messages,
            ),
        ).encodeToByteArray()
        // The single-source-of-truth field map: whatever ends up in `contextInfo`
        // on the wire below is exactly what gets bound into the ciphertext here.
        val ciphertext = encryptor.encrypt(plaintext, ContextInfo.canonicalBytes(contextInfo.toContextFields()))

        val request = UploadBatchRequest(
            version = PROTOCOL_VERSION,
            deviceTime = Instant.now().toString(),
            clientBatchId = batch.clientBatchId,
            encryption = EncryptionMeta(BatchEncryptor.SCHEME, serverKeyId, serverKeyPin),
            ciphertext = Base64.getUrlEncoder().withoutPadding().encodeToString(ciphertext),
            contextInfo = contextInfo,
        )

        return try {
            val response = ingestApi.uploadBatch(request)
            recordUploadedDedupeIds(messages, response)
            pendingBatchDao.update(
                batch.copy(state = PendingBatchEntity.STATE_SENT, updatedAtEpochMillis = System.currentTimeMillis()),
            )
            true
        } catch (exc: HttpException) {
            markRetry(batch, "http_${exc.code()}")
            false
        } catch (exc: IOException) {
            markRetry(batch, exc.javaClass.simpleName)
            false
        }
    }

    /** Records every message the backend didn't reject — accepted or duplicate alike — as uploaded. */
    private suspend fun recordUploadedDedupeIds(messages: List<SmsRecord>, response: UploadResponse) {
        val now = System.currentTimeMillis()
        val rejectedIds = response.rejected.map { it.clientMessageId }.toSet()
        for (message in messages) {
            if (message.clientMessageId !in rejectedIds) {
                uploadedDedupeDao.insert(UploadedDedupeIdEntity(message.dedupeId, now))
            }
        }
    }

    private suspend fun markRetry(batch: PendingBatchEntity, reason: String) {
        pendingBatchDao.update(
            batch.copy(
                retryCount = batch.retryCount + 1,
                lastError = reason,
                updatedAtEpochMillis = System.currentTimeMillis(),
            ),
        )
    }

    companion object {
        const val PROTOCOL_VERSION = 1
    }
}
