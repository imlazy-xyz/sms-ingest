package xyz.imlazy.smsingest.sync

import com.google.crypto.tink.CleartextKeysetHandle
import com.google.crypto.tink.HybridDecrypt
import com.google.crypto.tink.JsonKeysetReader
import java.nio.charset.StandardCharsets
import java.util.Base64
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import xyz.imlazy.smsingest.crypto.ContextInfo
import xyz.imlazy.smsingest.crypto.CryptoConfig
import xyz.imlazy.smsingest.data.PendingBatchDao
import xyz.imlazy.smsingest.data.PendingBatchEntity
import xyz.imlazy.smsingest.data.UploadedDedupeDao
import xyz.imlazy.smsingest.data.UploadedDedupeIdEntity
import xyz.imlazy.smsingest.network.UploadBatchRequest
import xyz.imlazy.smsingest.network.createIngestApi
import xyz.imlazy.smsingest.setup.CredentialStore
import xyz.imlazy.smsingest.setup.ProvisioningPayload
import xyz.imlazy.smsingest.sms.SmsRecord

private class FakePendingBatchDao(initial: List<PendingBatchEntity> = emptyList()) : PendingBatchDao {
    val rows = initial.associateBy { it.clientBatchId }.toMutableMap()

    override suspend fun insert(batch: PendingBatchEntity) {
        rows[batch.clientBatchId] = batch
    }

    override suspend fun update(batch: PendingBatchEntity) {
        rows[batch.clientBatchId] = batch
    }

    override suspend fun delete(batch: PendingBatchEntity) {
        rows.remove(batch.clientBatchId)
    }

    override suspend fun getByClientBatchId(clientBatchId: String): PendingBatchEntity? = rows[clientBatchId]

    override fun observeByState(state: String): Flow<List<PendingBatchEntity>> =
        flowOf(rows.values.filter { it.state == state })

    override suspend fun getByState(state: String): List<PendingBatchEntity> =
        rows.values.filter { it.state == state }.sortedBy { it.createdAtEpochMillis }

    override fun observeMostRecent(): Flow<PendingBatchEntity?> =
        flowOf(rows.values.maxByOrNull { it.updatedAtEpochMillis })
}

private class FakeUploadedDedupeDao : UploadedDedupeDao {
    val inserted = mutableListOf<UploadedDedupeIdEntity>()
    override suspend fun insert(entry: UploadedDedupeIdEntity) {
        inserted += entry
    }

    override suspend fun exists(dedupeId: String): Boolean = inserted.any { it.dedupeId == dedupeId }

    override fun observeCount(): Flow<Int> = flowOf(inserted.size)
}

private class FakeCredentialStore(
    private val apiBaseUrl: String?,
    private val publicKeysetJson: String?,
) : CredentialStore {
    override fun isProvisioned(): Boolean = apiBaseUrl != null
    override fun save(payload: ProvisioningPayload, publicKeysetJson: String) = Unit
    override fun getApiBaseUrl(): String? = apiBaseUrl
    override fun getServerKeyId(): String? = apiBaseUrl?.let { "server-key-2026-05" }
    override fun getServerKeyPin(): String? = apiBaseUrl?.let { "pin" }
    override fun getPublicKeysetJson(): String? = publicKeysetJson
    override fun getDeviceToken(): String? = apiBaseUrl?.let { "device-token" }
    override fun getDeviceDedupeSecret(): String? = apiBaseUrl?.let { "dedupe-secret" }
    override fun isBackfillComplete(): Boolean = false
    override fun markBackfillComplete() = Unit
}

private class FixedDeviceInfoProvider : DeviceInfoProvider {
    override fun current(): DeviceInfo = DeviceInfo(appInstanceId = "instance-1", androidSdk = 35, appVersion = "0.1.0")
}

private fun pendingBatch(clientBatchId: String, messages: List<SmsRecord>) = PendingBatchEntity(
    clientBatchId = clientBatchId,
    messagesJson = Json.encodeToString(messages),
    state = PendingBatchEntity.STATE_PENDING,
    createdAtEpochMillis = 1_000,
    updatedAtEpochMillis = 1_000,
)

private fun sampleMessage(id: String) = SmsRecord(
    clientMessageId = id,
    dedupeId = "dedupe-$id",
    direction = SmsRecord.DIRECTION_INBOX,
    sender = "+15551234567",
    body = "hello",
    smsReceivedAt = "2026-05-23T12:00:00Z",
)

private fun acceptedBody() = """
    {"status":"accepted","server_batch_id":"b1","accepted_count":1,
     "duplicate_count":0,"rejected_count":0,"rejected":[],
     "next_sync":{"retry_after_seconds":null}}
""".trimIndent()

// Same fixture keypair as crypto/CryptoInteropTest.kt, so a decrypt here proves
// against real Tink HPKE (not just string matching) that the context_info this
// class puts on the wire is exactly what it bound into the ciphertext.
private const val PUBLIC_KEYSET_JSON = """{
  "primaryKeyId": 1016539568,
  "key": [
    {
      "keyData": {
        "typeUrl": "type.googleapis.com/google.crypto.tink.HpkePublicKey",
        "value": "EgYIARABGAIaIKdW1QhtSFhEDibqxtx2ZESD9v+hsVJMbYIMEaBSiiYj",
        "keyMaterialType": "ASYMMETRIC_PUBLIC"
      },
      "status": "ENABLED",
      "keyId": 1016539568,
      "outputPrefixType": "TINK"
    }
  ]
}"""

private const val PRIVATE_KEYSET_JSON = """{
  "primaryKeyId": 1016539568,
  "key": [
    {
      "keyData": {
        "typeUrl": "type.googleapis.com/google.crypto.tink.HpkePrivateKey",
        "value": "EioSBggBEAEYAhogp1bVCG1IWEQOJurG3HZkRIP2/6GxUkxtggwRoFKKJiMaIGfvRBv5gUXmEMM0MDaQhx0e543IwbN1oz9YlIqCCn+S",
        "keyMaterialType": "ASYMMETRIC_PRIVATE"
      },
      "status": "ENABLED",
      "keyId": 1016539568,
      "outputPrefixType": "TINK"
    }
  ]
}"""

class BatchSyncerTest {

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        CryptoConfig.ensureRegistered()
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun syncer(
        pendingBatchDao: PendingBatchDao,
        uploadedDedupeDao: UploadedDedupeDao = FakeUploadedDedupeDao(),
        credentialStore: CredentialStore = FakeCredentialStore(server.url("/").toString(), PUBLIC_KEYSET_JSON),
    ) = BatchSyncer(
        pendingBatchDao = pendingBatchDao,
        uploadedDedupeDao = uploadedDedupeDao,
        credentialStore = credentialStore,
        ingestApiProvider = {
            credentialStore.getApiBaseUrl()?.let { createIngestApi(it) { credentialStore.getDeviceToken() } }
        },
        deviceInfoProvider = FixedDeviceInfoProvider(),
    )

    private fun hybridDecrypt(): HybridDecrypt =
        CleartextKeysetHandle.read(JsonKeysetReader.withString(PRIVATE_KEYSET_JSON))
            .getPrimitive(HybridDecrypt::class.java)

    private fun b64UrlDecode(value: String): ByteArray {
        val padded = value + "=".repeat((4 - value.length % 4) % 4)
        return Base64.getUrlDecoder().decode(padded)
    }

    @Test
    fun `does nothing when not provisioned`() = runTest {
        val pendingBatchDao = FakePendingBatchDao(listOf(pendingBatch("b1", listOf(sampleMessage("m1")))))

        val result = syncer(pendingBatchDao, credentialStore = FakeCredentialStore(null, null)).sync()

        assertEquals(SyncResult.NOT_PROVISIONED, result)
    }

    @Test
    fun `succeeds with an empty queue`() = runTest {
        val result = syncer(FakePendingBatchDao()).sync()

        assertEquals(SyncResult.SUCCESS, result)
    }

    @Test
    fun `uploads a pending batch, marks it sent, and records its dedupe id as uploaded`() = runTest {
        server.enqueue(MockResponse().setBody(acceptedBody()))
        val pendingBatchDao = FakePendingBatchDao(listOf(pendingBatch("b1", listOf(sampleMessage("m1")))))
        val uploadedDedupeDao = FakeUploadedDedupeDao()

        val result = syncer(pendingBatchDao, uploadedDedupeDao).sync()

        assertEquals(SyncResult.SUCCESS, result)
        assertEquals(PendingBatchEntity.STATE_SENT, pendingBatchDao.rows.getValue("b1").state)
        assertTrue(uploadedDedupeDao.inserted.any { it.dedupeId == "dedupe-m1" })

        val recorded = server.takeRequest()
        assertEquals("/v1/uploads/sms-batches", recorded.path)
        assertEquals("Bearer device-token", recorded.getHeader("Authorization"))
    }

    @Test
    fun `does not record a rejected message's dedupe id but still marks the batch sent`() = runTest {
        server.enqueue(
            MockResponse().setBody(
                """
                {"status":"partial","server_batch_id":"b1","accepted_count":0,
                 "duplicate_count":0,"rejected_count":1,
                 "rejected":[{"client_message_id":"m1","reason":"invalid_timestamp"}],
                 "next_sync":{"retry_after_seconds":null}}
                """.trimIndent(),
            ),
        )
        val pendingBatchDao = FakePendingBatchDao(listOf(pendingBatch("b1", listOf(sampleMessage("m1")))))
        val uploadedDedupeDao = FakeUploadedDedupeDao()

        val result = syncer(pendingBatchDao, uploadedDedupeDao).sync()

        assertEquals(SyncResult.SUCCESS, result)
        assertTrue(uploadedDedupeDao.inserted.isEmpty())
        assertEquals(PendingBatchEntity.STATE_SENT, pendingBatchDao.rows.getValue("b1").state)
    }

    @Test
    fun `leaves a batch pending with an incremented retry count on a server error`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))
        val pendingBatchDao = FakePendingBatchDao(listOf(pendingBatch("b1", listOf(sampleMessage("m1")))))

        val result = syncer(pendingBatchDao).sync()

        assertEquals(SyncResult.RETRY, result)
        val batch = pendingBatchDao.rows.getValue("b1")
        assertEquals(PendingBatchEntity.STATE_PENDING, batch.state)
        assertEquals(1, batch.retryCount)
        assertEquals("http_500", batch.lastError)
    }

    @Test
    fun `processes remaining batches even after one fails`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))
        server.enqueue(MockResponse().setBody(acceptedBody()))
        val pendingBatchDao = FakePendingBatchDao(
            listOf(
                pendingBatch("b1", listOf(sampleMessage("m1"))).copy(createdAtEpochMillis = 1_000),
                pendingBatch("b2", listOf(sampleMessage("m2"))).copy(createdAtEpochMillis = 2_000),
            ),
        )

        val result = syncer(pendingBatchDao).sync()

        assertEquals(SyncResult.RETRY, result)
        assertEquals(PendingBatchEntity.STATE_PENDING, pendingBatchDao.rows.getValue("b1").state)
        assertEquals(PendingBatchEntity.STATE_SENT, pendingBatchDao.rows.getValue("b2").state)
    }

    @Test
    fun `HPKE-decrypts the uploaded ciphertext using the context_info bytes present in the same request body`() =
        runTest {
            server.enqueue(MockResponse().setBody(acceptedBody()))
            val pendingBatchDao = FakePendingBatchDao(listOf(pendingBatch("b1", listOf(sampleMessage("m1")))))

            syncer(pendingBatchDao).sync()

            val recorded = server.takeRequest()
            val request = Json { ignoreUnknownKeys = true }
                .decodeFromString<UploadBatchRequest>(recorded.body.readUtf8())
            val contextBytes = ContextInfo.canonicalBytes(request.contextInfo.toContextFields())
            val ciphertext = b64UrlDecode(request.ciphertext)

            val plaintext = String(hybridDecrypt().decrypt(ciphertext, contextBytes), StandardCharsets.UTF_8)

            assertTrue(plaintext.contains(""""dedupe_id":"dedupe-m1""""))
        }
}
