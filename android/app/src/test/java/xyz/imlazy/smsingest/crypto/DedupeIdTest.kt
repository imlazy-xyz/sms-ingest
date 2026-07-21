package xyz.imlazy.smsingest.crypto

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class DedupeIdTest {

    private val secret = "device-dedupe-secret"

    // 2026-07-01T12:00:00Z
    private val whenMillis = 1782907200000L

    @Test
    fun canonicalStringFormat() {
        val s = DedupeId.canonicalString("inbox", "+15551230000", whenMillis, "hello")
        assertEquals(
            "v1\n" +
                "direction=inbox\n" +
                "sender=+15551230000\n" +
                "sms_received_at=$whenMillis\n" +
                "body=hello\n",
            s,
        )
    }

    @Test
    fun senderNormalizationTrimsWhitespace() {
        assertEquals("+1555", DedupeId.normalizeSender("  +1555  "))
        val a = DedupeId.compute(secret, "inbox", "  +1555  ", whenMillis, "hi")
        val b = DedupeId.compute(secret, "inbox", "+1555", whenMillis, "hi")
        assertEquals(a, b)
    }

    @Test
    fun dedupeIdIsStableAndContentSensitive() {
        val a = DedupeId.compute(secret, "inbox", "+1555", whenMillis, "hello")
        val b = DedupeId.compute(secret, "inbox", "+1555", whenMillis, "hello")
        assertEquals(a, b) // stable across retries

        val differentBody = DedupeId.compute(secret, "inbox", "+1555", whenMillis, "hell0")
        assertNotEquals(a, differentBody)

        val differentSecret = DedupeId.compute("other", "inbox", "+1555", whenMillis, "hello")
        assertNotEquals(a, differentSecret)
    }

    /**
     * Known-answer vector cross-checked against the backend's
     * `backend/app/core/dedupe.py::compute_dedupe_id` for the same inputs
     * (computed directly with Python's hmac/hashlib/base64, not copied from
     * a backend test). Catches any byte-level divergence between the two
     * implementations that unit tests within one language alone would miss.
     */
    @Test
    fun matchesBackendKnownAnswerVector() {
        val dedupeId = DedupeId.compute(secret, "inbox", "+1555", whenMillis, "hello")
        assertEquals("lj9YT-_bq063X4udJZSRxwzqaqHNzAmAyrBprLH5UAg", dedupeId)
    }
}
