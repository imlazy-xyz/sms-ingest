package xyz.imlazy.smsingest.network

import org.junit.Assert.assertEquals
import org.junit.Test
import xyz.imlazy.smsingest.crypto.ContextInfo

/**
 * Guards the Phase 7 shared-source-of-truth fix: [UploadContextInfo.toContextFields]
 * must produce the exact field names/values that end up in the wire
 * `context_info` object, since that's what gets bound into the HPKE
 * ciphertext (`xyz.imlazy.smsingest.sync.BatchSyncer`). This fixture matches
 * `crypto/CryptoInteropTest.kt`'s backend-verified canonical bytes.
 */
class UploadModelsTest {

    @Test
    fun `toContextFields canonicalizes to the exact backend-verified bytes`() {
        val contextInfo = UploadContextInfo(
            apiBaseUrl = "https://sms-api.example.com",
            payloadType = UploadContextInfo.PAYLOAD_TYPE_SMS_BATCH,
            version = 1,
            clientBatchId = "fixture-batch-0001",
        )

        val bytes = ContextInfo.canonicalBytes(contextInfo.toContextFields())

        assertEquals(
            """{"api_base_url":"https://sms-api.example.com","client_batch_id":"fixture-batch-0001","payload_type":"sms_batch","version":1}""",
            String(bytes, Charsets.UTF_8),
        )
    }
}
