package xyz.imlazy.smsingest.setup

import java.util.Base64
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Wire shape of the provisioning QR JSON, per
 * projects/sms-ingest/docs/backend-plan.md § Provisioning QR. Field names and
 * `v` must match `backend/app/services/provisioning.py::build_qr_payload`
 * exactly.
 */
@Serializable
data class ProvisioningPayload(
    val v: Int,
    @SerialName("api_base_url") val apiBaseUrl: String,
    @SerialName("device_id") val deviceId: String,
    @SerialName("device_token") val deviceToken: String,
    @SerialName("device_dedupe_secret") val deviceDedupeSecret: String,
    @SerialName("server_key_id") val serverKeyId: String,
    @SerialName("server_key_pin") val serverKeyPin: String,
    @SerialName("issued_at") val issuedAt: String,
)

/**
 * Parses and structurally validates a scanned QR payload. This only checks
 * shape (required fields present and well-formed) — it does not verify
 * `server_key_pin` against the backend's actual public keyset, because the QR
 * carries only the pin (a fingerprint), not keyset material, and no endpoint
 * currently serves it. See projects/sms-ingest/open-questions.md
 * ("keyset delivery for pin verification") for that gap; Phase 4/5 must
 * resolve it before the pin can be compared against anything.
 *
 * Never include the raw payload or any field value in a returned error —
 * callers must not log it either (docs/backend-plan.md: "Do not log QR
 * payloads").
 */
object ProvisioningPayloadParser {

    private const val SUPPORTED_VERSION = 1

    /** Length in bytes of a SHA-256 digest, the expected decoded `server_key_pin` size. */
    private const val KEY_PIN_DIGEST_BYTES = 32

    private val json = Json { ignoreUnknownKeys = true }

    fun parse(raw: String): Result<ProvisioningPayload> {
        val payload =
            try {
                json.decodeFromString<ProvisioningPayload>(raw)
            } catch (exc: Exception) {
                return Result.failure(IllegalArgumentException("malformed provisioning QR JSON", exc))
            }
        return validate(payload)
    }

    private fun validate(payload: ProvisioningPayload): Result<ProvisioningPayload> {
        if (payload.v != SUPPORTED_VERSION) {
            return Result.failure(
                IllegalArgumentException("unsupported provisioning payload version: ${payload.v}"),
            )
        }
        val blankField = listOf(
            "api_base_url" to payload.apiBaseUrl,
            "device_id" to payload.deviceId,
            "device_token" to payload.deviceToken,
            "device_dedupe_secret" to payload.deviceDedupeSecret,
            "server_key_id" to payload.serverKeyId,
            "server_key_pin" to payload.serverKeyPin,
            "issued_at" to payload.issuedAt,
        ).firstOrNull { (_, value) -> value.isBlank() }
        if (blankField != null) {
            return Result.failure(IllegalArgumentException("missing required field: ${blankField.first}"))
        }
        if (!payload.apiBaseUrl.startsWith("https://")) {
            return Result.failure(IllegalArgumentException("api_base_url must be https"))
        }
        if (decodedKeyPinLength(payload.serverKeyPin) != KEY_PIN_DIGEST_BYTES) {
            return Result.failure(IllegalArgumentException("server_key_pin is not a valid base64url SHA-256 fingerprint"))
        }
        return Result.success(payload)
    }

    private fun decodedKeyPinLength(pin: String): Int =
        try {
            Base64.getUrlDecoder().decode(padBase64Url(pin)).size
        } catch (_: IllegalArgumentException) {
            -1
        }

    /** `server_key_pin` is unpadded base64url (matches backend's `_b64url_nopad`); restore padding for `java.util.Base64`. */
    private fun padBase64Url(value: String): String {
        val remainder = value.length % 4
        return if (remainder == 0) value else value + "=".repeat(4 - remainder)
    }
}
