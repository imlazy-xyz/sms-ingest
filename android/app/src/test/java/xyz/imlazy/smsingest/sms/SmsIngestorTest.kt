package xyz.imlazy.smsingest.sms

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import xyz.imlazy.smsingest.crypto.DedupeId
import xyz.imlazy.smsingest.data.PendingBatchDao
import xyz.imlazy.smsingest.data.PendingBatchEntity
import xyz.imlazy.smsingest.data.UploadedDedupeDao
import xyz.imlazy.smsingest.data.UploadedDedupeIdEntity
import xyz.imlazy.smsingest.setup.CredentialStore
import xyz.imlazy.smsingest.setup.ProvisioningPayload

private class FakePendingBatchDao : PendingBatchDao {
    val inserted = mutableListOf<PendingBatchEntity>()

    override suspend fun insert(batch: PendingBatchEntity) {
        inserted += batch
    }

    override suspend fun update(batch: PendingBatchEntity) = Unit
    override suspend fun delete(batch: PendingBatchEntity) = Unit
    override suspend fun getByClientBatchId(clientBatchId: String): PendingBatchEntity? =
        inserted.find { it.clientBatchId == clientBatchId }

    override fun observeByState(state: String): Flow<List<PendingBatchEntity>> = flowOf(emptyList())
}

private class FakeUploadedDedupeDao(private val existing: Set<String> = emptySet()) : UploadedDedupeDao {
    override suspend fun insert(entry: UploadedDedupeIdEntity) = Unit
    override suspend fun exists(dedupeId: String): Boolean = dedupeId in existing
}

private class FakeCredentialStore(private val dedupeSecret: String?) : CredentialStore {
    override fun isProvisioned(): Boolean = dedupeSecret != null
    override fun save(payload: ProvisioningPayload, publicKeysetJson: String) = Unit
    override fun getApiBaseUrl(): String? = null
    override fun getServerKeyId(): String? = null
    override fun getServerKeyPin(): String? = null
    override fun getPublicKeysetJson(): String? = null
    override fun getDeviceToken(): String? = null
    override fun getDeviceDedupeSecret(): String? = dedupeSecret
}

class SmsIngestorTest {

    private fun capture(
        sender: String = " +15551234567 ",
        body: String = "hello",
        epochMillis: Long = 1_748_000_000_000,
    ) = SmsCapture(sender = sender, body = body, smsReceivedAtEpochMillis = epochMillis)

    private fun expectedDedupeId(secret: String, capture: SmsCapture) = DedupeId.compute(
        dedupeSecret = secret,
        direction = SmsRecord.DIRECTION_INBOX,
        sender = DedupeId.normalizeSender(capture.sender),
        smsReceivedAtEpochMillis = capture.smsReceivedAtEpochMillis,
        body = capture.body,
    )

    @Test
    fun `queues a new pending batch with the exact wire field names`() = runTest {
        val pendingBatchDao = FakePendingBatchDao()
        val ingestor = SmsIngestor(pendingBatchDao, FakeUploadedDedupeDao(), FakeCredentialStore("secret"))

        ingestor.enqueue(listOf(capture()))

        assertEquals(1, pendingBatchDao.inserted.size)
        val batch = pendingBatchDao.inserted.single()
        assertEquals(PendingBatchEntity.STATE_PENDING, batch.state)
        val json = batch.messagesJson
        assertTrue(json.contains(""""direction":"inbox""""))
        assertTrue(json.contains(""""sender":"+15551234567""""))
        assertTrue(json.contains(""""body":"hello""""))
        assertTrue(json.contains(""""dedupe_id""""))
        assertTrue(json.contains(""""client_message_id""""))
        assertTrue(json.contains(""""sms_received_at""""))
    }

    @Test
    fun `computes the same dedupe id DedupeId would compute directly`() = runTest {
        val secret = "secret"
        val cap = capture()
        val pendingBatchDao = FakePendingBatchDao()
        val ingestor = SmsIngestor(pendingBatchDao, FakeUploadedDedupeDao(), FakeCredentialStore(secret))

        ingestor.enqueue(listOf(cap))

        val expected = expectedDedupeId(secret, cap)
        assertTrue(pendingBatchDao.inserted.single().messagesJson.contains(""""dedupe_id":"$expected""""))
    }

    @Test
    fun `skips a message whose dedupe id was already uploaded`() = runTest {
        val secret = "secret"
        val cap = capture()
        val pendingBatchDao = FakePendingBatchDao()
        val ingestor = SmsIngestor(
            pendingBatchDao,
            FakeUploadedDedupeDao(setOf(expectedDedupeId(secret, cap))),
            FakeCredentialStore(secret),
        )

        ingestor.enqueue(listOf(cap))

        assertTrue(pendingBatchDao.inserted.isEmpty())
    }

    @Test
    fun `does nothing when not yet provisioned`() = runTest {
        val pendingBatchDao = FakePendingBatchDao()
        val ingestor = SmsIngestor(pendingBatchDao, FakeUploadedDedupeDao(), FakeCredentialStore(dedupeSecret = null))

        ingestor.enqueue(listOf(capture()))

        assertTrue(pendingBatchDao.inserted.isEmpty())
    }

    @Test
    fun `does nothing on an empty capture list`() = runTest {
        val pendingBatchDao = FakePendingBatchDao()
        val ingestor = SmsIngestor(pendingBatchDao, FakeUploadedDedupeDao(), FakeCredentialStore("secret"))

        ingestor.enqueue(emptyList())

        assertTrue(pendingBatchDao.inserted.isEmpty())
    }
}
