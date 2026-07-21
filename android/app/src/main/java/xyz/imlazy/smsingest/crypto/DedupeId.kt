package xyz.imlazy.smsingest.crypto

import java.nio.charset.StandardCharsets
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * HMAC dedupe fingerprints. Canonical string and HMAC construction must stay
 * byte-for-byte compatible with the backend's `backend/app/core/dedupe.py`,
 * per `projects/sms-ingest/docs/backend-plan.md` § Crypto Formats.
 *
 * Uses `java.util.Base64`/`javax.crypto.Mac` (not `android.util.Base64`) so
 * this is plain-JVM code: it runs under `testDebugUnitTest` without an
 * Android runtime, and identically on-device.
 */
object DedupeId {

    private const val ALGORITHM = "HmacSHA256"

    fun normalizeSender(sender: String): String = sender.trim()

    fun canonicalString(
        direction: String,
        sender: String,
        smsReceivedAtEpochMillis: Long,
        body: String,
    ): String = buildString {
        append("v1\n")
        append("direction=").append(direction).append('\n')
        append("sender=").append(normalizeSender(sender)).append('\n')
        append("sms_received_at=").append(smsReceivedAtEpochMillis).append('\n')
        append("body=").append(body).append('\n')
    }

    fun compute(
        dedupeSecret: String,
        direction: String,
        sender: String,
        smsReceivedAtEpochMillis: Long,
        body: String,
    ): String {
        val canonical = canonicalString(direction, sender, smsReceivedAtEpochMillis, body)
        val mac = Mac.getInstance(ALGORITHM)
        mac.init(SecretKeySpec(dedupeSecret.toByteArray(StandardCharsets.UTF_8), ALGORITHM))
        val digest = mac.doFinal(canonical.toByteArray(StandardCharsets.UTF_8))
        return Base64.getUrlEncoder().withoutPadding().encodeToString(digest)
    }
}
