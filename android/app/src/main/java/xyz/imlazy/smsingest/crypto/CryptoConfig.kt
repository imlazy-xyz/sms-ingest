package xyz.imlazy.smsingest.crypto

import com.google.crypto.tink.hybrid.HybridConfig

/**
 * Registers Tink's hybrid (HPKE) primitives. Tink requires this once per
 * process before any keyset can produce a `HybridEncrypt`/`HybridDecrypt`
 * primitive; the backend does the equivalent `hybrid.register()`. Idempotent
 * and safe to call from multiple entry points (AppContainer init, tests).
 */
object CryptoConfig {

    fun ensureRegistered() {
        HybridConfig.register()
    }
}
