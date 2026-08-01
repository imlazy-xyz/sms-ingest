package xyz.imlazy.smsingest.network

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException

class IngestApiTest {

    private lateinit var server: MockWebServer
    private lateinit var api: IngestApi

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        api = createIngestApi(server.url("/").toString()) { "test-device-token" }
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun sampleRequest() = UploadBatchRequest(
        version = 1,
        deviceTime = "2026-05-23T12:00:00Z",
        clientBatchId = "batch-1",
        encryption = EncryptionMeta(
            scheme = "tink-hpke-x25519-aes256gcm-v1",
            serverKeyId = "server-key-2026-05",
            serverKeyPin = "pin",
        ),
        ciphertext = "cGxhaW50ZXh0",
        contextInfo = UploadContextInfo(
            apiBaseUrl = "https://sms-api.example.com",
            payloadType = "sms_batch",
            version = 1,
            clientBatchId = "batch-1",
        ),
    )

    private fun acceptedBody() = """
        {"status":"accepted","server_batch_id":"b1","accepted_count":1,
         "duplicate_count":0,"rejected_count":0,"rejected":[],
         "next_sync":{"retry_after_seconds":null}}
    """.trimIndent()

    @Test
    fun `attaches the bearer token and posts to the upload path`() = runTest {
        server.enqueue(MockResponse().setBody(acceptedBody()))

        val response = api.uploadBatch(sampleRequest())

        val recorded = server.takeRequest()
        assertEquals("/v1/uploads/sms-batches", recorded.path)
        assertEquals("Bearer test-device-token", recorded.getHeader("Authorization"))
        assertEquals("accepted", response.status)
        assertEquals(1, response.acceptedCount)
    }

    @Test
    fun `request body uses the exact snake_case field names the backend expects`() = runTest {
        server.enqueue(MockResponse().setBody(acceptedBody()))

        api.uploadBatch(sampleRequest())

        val body = server.takeRequest().body.readUtf8()
        assertTrue(body.contains(""""client_batch_id":"batch-1""""))
        assertTrue(body.contains(""""device_time":"2026-05-23T12:00:00Z""""))
        assertTrue(body.contains(""""server_key_id":"server-key-2026-05""""))
        assertTrue(body.contains(""""server_key_pin":"pin""""))
        assertTrue(body.contains(""""context_info""""))
        assertTrue(body.contains(""""api_base_url":"https://sms-api.example.com""""))
        assertTrue(body.contains(""""payload_type":"sms_batch""""))
    }

    @Test
    fun `parses a partial response with rejected items`() = runTest {
        server.enqueue(
            MockResponse().setBody(
                """
                {"status":"partial","server_batch_id":"b2","accepted_count":1,
                 "duplicate_count":0,"rejected_count":1,
                 "rejected":[{"client_message_id":"m1","reason":"invalid_timestamp"}],
                 "next_sync":{"retry_after_seconds":30}}
                """.trimIndent(),
            ),
        )

        val response = api.uploadBatch(sampleRequest())

        assertEquals("partial", response.status)
        assertEquals(1, response.rejected.size)
        assertEquals("m1", response.rejected.first().clientMessageId)
        assertEquals("invalid_timestamp", response.rejected.first().reason)
        assertEquals(30, response.nextSync.retryAfterSeconds)
    }

    @Test(expected = HttpException::class)
    fun `throws on a 401 unauthorized response`() = runTest {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"unauthorized"}"""))

        api.uploadBatch(sampleRequest())
    }

    @Test(expected = HttpException::class)
    fun `throws on a 400 rejected response`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(400)
                .setBody("""{"status":"rejected","reason":"invalid_batch"}"""),
        )

        api.uploadBatch(sampleRequest())
    }
}
