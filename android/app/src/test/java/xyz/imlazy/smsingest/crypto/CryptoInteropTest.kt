package xyz.imlazy.smsingest.crypto

import com.google.crypto.tink.CleartextKeysetHandle
import com.google.crypto.tink.HybridDecrypt
import com.google.crypto.tink.JsonKeysetReader
import java.nio.charset.StandardCharsets
import java.util.Base64
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.BeforeClass
import org.junit.Test

/**
 * Cross-language interop against a fixture round-tripped through the real
 * backend `crypto.py`. Proves the Kotlin encrypt/pin/context-info paths agree
 * with the Python decrypt side byte-for-byte. Runs on plain JVM (cleartext
 * keysets, Tink's own X25519 HPKE — no `android.*`).
 */
class CryptoInteropTest {

    companion object {
        @BeforeClass
        @JvmStatic
        fun registerTink() {
            CryptoConfig.ensureRegistered()
        }

        // language=JSON
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

        // language=JSON
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

        private const val SERVER_KEY_PIN = "2-M8m7RhNff0SYqHYd-EUz-iajiUYRflP0iFKrUYfGY"

        private val CONTEXT_INFO: Map<String, Any> = mapOf(
            "api_base_url" to "https://sms-api.example.com",
            "payload_type" to "sms_batch",
            "version" to 1,
            "client_batch_id" to "fixture-batch-0001",
        )

        private const val CONTEXT_INFO_CANONICAL =
            """{"api_base_url":"https://sms-api.example.com","client_batch_id":"fixture-batch-0001","payload_type":"sms_batch","version":1}"""

        private const val PLAINTEXT = """{"schema_version":1,"messages":[]}"""

        private const val CIPHERTEXT_B64URL =
            "ATyXKbCbIC-gv2ww0px7cIFGEMLcbO50uwUUzIxnIA2AyiDhLQ2GPWrt_vG7NrfKrgyLI4HXJlAGxmKYSB5sEpogLR0ZvgdDsvExCgyM6kiqoy2ME2gq"
    }

    private fun hybridDecrypt(): HybridDecrypt =
        CleartextKeysetHandle.read(JsonKeysetReader.withString(PRIVATE_KEYSET_JSON))
            .getPrimitive(HybridDecrypt::class.java)

    private fun b64UrlDecode(value: String): ByteArray {
        val padded = value + "=".repeat((4 - value.length % 4) % 4)
        return Base64.getUrlDecoder().decode(padded)
    }

    @Test
    fun keysetPinMatchesBackend() {
        assertEquals(SERVER_KEY_PIN, KeysetPin.compute(PUBLIC_KEYSET_JSON))
    }

    @Test
    fun contextInfoCanonicalizationMatchesBackend() {
        val bytes = ContextInfo.canonicalBytes(CONTEXT_INFO)
        assertEquals(CONTEXT_INFO_CANONICAL, String(bytes, StandardCharsets.UTF_8))
    }

    @Test
    fun encryptThenDecryptRecoversPlaintext() {
        val context = ContextInfo.canonicalBytes(CONTEXT_INFO)
        val plaintext = PLAINTEXT.toByteArray(StandardCharsets.UTF_8)

        val ciphertext = BatchEncryptor.fromPublicKeysetJson(PUBLIC_KEYSET_JSON)
            .encrypt(plaintext, context)
        val recovered = hybridDecrypt().decrypt(ciphertext, context)

        assertArrayEquals(plaintext, recovered)
    }

    @Test
    fun decryptsBackendGeneratedCiphertext() {
        val context = ContextInfo.canonicalBytes(CONTEXT_INFO)
        val recovered = hybridDecrypt().decrypt(b64UrlDecode(CIPHERTEXT_B64URL), context)
        assertEquals(PLAINTEXT, String(recovered, StandardCharsets.UTF_8))
    }
}
