package xyz.imlazy.smsingest.network

import java.io.IOException
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test

class AuthInterceptorTest {

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `adds the Authorization header with the current token`() {
        server.enqueue(MockResponse().setBody("ok"))
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor { "abc123" })
            .build()

        client.newCall(Request.Builder().url(server.url("/")).build()).execute().close()

        assertEquals("Bearer abc123", server.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `re-reads the token on every request rather than caching it`() {
        server.enqueue(MockResponse().setBody("ok"))
        server.enqueue(MockResponse().setBody("ok"))
        var token = "first"
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor { token })
            .build()

        client.newCall(Request.Builder().url(server.url("/")).build()).execute().close()
        token = "second"
        client.newCall(Request.Builder().url(server.url("/")).build()).execute().close()

        assertEquals("Bearer first", server.takeRequest().getHeader("Authorization"))
        assertEquals("Bearer second", server.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `fails closed when no token is stored`() {
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor { null })
            .build()

        assertThrows(IOException::class.java) {
            client.newCall(Request.Builder().url(server.url("/")).build()).execute()
        }
    }
}
