package xyz.imlazy.smsingest.crypto

import com.google.crypto.tink.CleartextKeysetHandle
import com.google.crypto.tink.HybridEncrypt
import com.google.crypto.tink.JsonKeysetReader

/**
 * HPKE hybrid encryption of an SMS batch with the backend's public keyset.
 *
 * Scheme `tink-hpke-x25519-aes256gcm-v1`; the backend decrypts with the
 * matching private keyset via Tink `HybridDecrypt`. The `contextInfo` bytes are
 * bound into the ciphertext and must be byte-identical on both sides — build
 * them with [ContextInfo.canonicalBytes]. See
 * `backend/app/core/crypto.py::decrypt_batch`.
 *
 * Requires [xyz.imlazy.smsingest.crypto.CryptoConfig.ensureRegistered] to have
 * run (done once at app startup). Never log plaintext, ciphertext, or keyset
 * material.
 */
class BatchEncryptor private constructor(private val hybridEncrypt: HybridEncrypt) {

    /** Tink's HPKE ciphertext wire format for [plaintext] bound to [contextInfo]. */
    fun encrypt(plaintext: ByteArray, contextInfo: ByteArray): ByteArray =
        hybridEncrypt.encrypt(plaintext, contextInfo)

    companion object {
        fun fromPublicKeysetJson(publicKeysetJson: String): BatchEncryptor {
            val handle = CleartextKeysetHandle.read(JsonKeysetReader.withString(publicKeysetJson))
            return BatchEncryptor(handle.getPrimitive(HybridEncrypt::class.java))
        }
    }
}
