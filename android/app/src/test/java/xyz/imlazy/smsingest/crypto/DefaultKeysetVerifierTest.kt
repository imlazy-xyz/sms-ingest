package xyz.imlazy.smsingest.crypto

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Exercises the real [DefaultKeysetVerifier] (fetch + pin comparison)
 * end to end against a local server. `setup/SetupViewModelTest.kt` only
 * ever uses a [KeysetVerifier] fake, so this composition — [PublicKeyFetcher]
 * + [KeysetPin] + the constant-time pin comparison — had no coverage of its
 * own since Phase 4.
 */
class DefaultKeysetVerifierTest {

    private lateinit var server: MockWebServer
    private lateinit var verifier: DefaultKeysetVerifier

    @Before
    fun setUp() {
        CryptoConfig.ensureRegistered()
        server = MockWebServer()
        server.start()
        verifier = DefaultKeysetVerifier(PublicKeyFetcher())
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun enqueueResponse(publicKeysetJson: String, pin: String = EXPECTED_PIN) {
        server.enqueue(
            MockResponse().setBody(
                Json.encodeToString(
                    PublicKeyResponse(
                        scheme = BatchEncryptor.SCHEME,
                        serverKeyId = "server-key-2026-05",
                        serverKeyPin = pin,
                        publicKeysetJson = publicKeysetJson,
                    ),
                ),
            ),
        )
    }

    @Test
    fun `verifies when the fetched keyset's fingerprint matches the pin`() = runTest {
        enqueueResponse(PUBLIC_KEYSET_JSON)

        val result = verifier.verify(server.url("/").toString(), EXPECTED_PIN)

        assertEquals(KeysetVerification.Verified(PUBLIC_KEYSET_JSON), result)
    }

    @Test
    fun `reports a pin mismatch when the QR-provisioned pin differs from the fetched keyset`() = runTest {
        enqueueResponse(PUBLIC_KEYSET_JSON)

        val result = verifier.verify(server.url("/").toString(), "some-other-pin")

        assertEquals(KeysetVerification.PinMismatch, result)
    }

    @Test
    fun `reports unavailable on a server error`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))

        val result = verifier.verify(server.url("/").toString(), EXPECTED_PIN)

        assertTrue(result is KeysetVerification.Unavailable)
    }

    @Test
    fun `reports unavailable when the fetched keyset is not valid Tink JSON`() = runTest {
        enqueueResponse(publicKeysetJson = "not valid tink json")

        val result = verifier.verify(server.url("/").toString(), EXPECTED_PIN)

        assertEquals(KeysetVerification.Unavailable("invalid keyset"), result)
    }

    private companion object {
        // Same fixture keypair as crypto/CryptoInteropTest.kt.
        const val PUBLIC_KEYSET_JSON = """{
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

        const val EXPECTED_PIN = "2-M8m7RhNff0SYqHYd-EUz-iajiUYRflP0iFKrUYfGY"
    }
}
