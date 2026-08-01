package xyz.imlazy.smsingest.crypto

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/**
 * Exercises the real `GET /v1/public-key` fetch/parse path against a local
 * server. Previously only covered indirectly, via fakes of the
 * [KeysetVerifier] interface in `setup/SetupViewModelTest.kt` — this class
 * itself (the actual `HttpURLConnection` GET and JSON parsing) had no
 * coverage since Phase 4.
 */
class PublicKeyFetcherTest {

    private lateinit var server: MockWebServer
    private lateinit var fetcher: PublicKeyFetcher

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        fetcher = PublicKeyFetcher()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun sampleBody() = """
        {"scheme":"tink-hpke-x25519-aes256gcm-v1","server_key_id":"server-key-2026-05",
         "server_key_pin":"pin","public_keyset_json":"{}"}
    """.trimIndent()

    @Test
    fun `GETs the exact path and parses the response`() = runTest {
        server.enqueue(MockResponse().setBody(sampleBody()))

        val response = fetcher.fetch(server.url("/").toString())

        val recorded = server.takeRequest()
        assertEquals("GET", recorded.method)
        assertEquals("/v1/public-key", recorded.path)
        assertEquals("tink-hpke-x25519-aes256gcm-v1", response.scheme)
        assertEquals("server-key-2026-05", response.serverKeyId)
        assertEquals("pin", response.serverKeyPin)
        assertEquals("{}", response.publicKeysetJson)
    }

    @Test
    fun `requests the same path whether or not the base url has a trailing slash`() = runTest {
        server.enqueue(MockResponse().setBody(sampleBody()))

        fetcher.fetch(server.url("/").toString().trimEnd('/'))

        assertEquals("/v1/public-key", server.takeRequest().path)
    }

    @Test(expected = IllegalStateException::class)
    fun `throws on a non-200 response`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))

        fetcher.fetch(server.url("/").toString())
    }
}
