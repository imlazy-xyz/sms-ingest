package xyz.imlazy.smsingest.crypto

import java.nio.charset.StandardCharsets
import java.security.MessageDigest

/** Outcome of fetching the backend keyset and checking it against the QR pin. */
sealed interface KeysetVerification {
    /** Pin matched. Carries the verified public keyset JSON for the caller to use/persist. */
    data class Verified(val publicKeysetJson: String) : KeysetVerification

    /** Fetched keyset's fingerprint did not match the QR-provisioned pin. */
    data object PinMismatch : KeysetVerification

    /** Network/parse/crypto failure before a comparison could be made. */
    data class Unavailable(val reason: String) : KeysetVerification
}

/**
 * Fetches the backend public keyset and verifies it against the QR-provisioned
 * `server_key_pin` before the keyset is trusted for encryption (the
 * pin-verifies / key-travels-in-band pattern, like TLS pinning). Closes the pin
 * check that Phase 2 deferred.
 *
 * An interface so [xyz.imlazy.smsingest.setup.SetupViewModel] can be tested
 * without the network. Implementations never throw across this boundary and
 * never log keyset material or the pin.
 */
interface KeysetVerifier {
    suspend fun verify(apiBaseUrl: String, expectedPin: String): KeysetVerification
}

class DefaultKeysetVerifier(
    private val fetcher: PublicKeyFetcher = PublicKeyFetcher(),
) : KeysetVerifier {

    override suspend fun verify(apiBaseUrl: String, expectedPin: String): KeysetVerification {
        val response = try {
            fetcher.fetch(apiBaseUrl)
        } catch (exc: Exception) {
            return KeysetVerification.Unavailable(exc.javaClass.simpleName)
        }
        val computedPin = try {
            KeysetPin.compute(response.publicKeysetJson)
        } catch (exc: Exception) {
            return KeysetVerification.Unavailable("invalid keyset")
        }
        return if (constantTimeEquals(computedPin, expectedPin)) {
            KeysetVerification.Verified(response.publicKeysetJson)
        } else {
            KeysetVerification.PinMismatch
        }
    }

    /** Compare fingerprints without a length-independent short-circuit. */
    private fun constantTimeEquals(a: String, b: String): Boolean =
        MessageDigest.isEqual(
            a.toByteArray(StandardCharsets.UTF_8),
            b.toByteArray(StandardCharsets.UTF_8),
        )
}
