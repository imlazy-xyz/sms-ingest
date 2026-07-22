package xyz.imlazy.smsingest.crypto

import com.google.crypto.tink.BinaryKeysetWriter
import com.google.crypto.tink.CleartextKeysetHandle
import com.google.crypto.tink.JsonKeysetReader
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.Base64

/**
 * Fingerprint of the backend public keyset used for QR pin verification.
 *
 * Must match `backend/app/core/crypto.py::compute_key_pin` byte-for-byte:
 * read the JSON keyset, re-serialize it to Tink's *binary* keyset wire format,
 * SHA-256 those bytes, then base64url-encode without padding. Any other
 * serialization (e.g. hashing the JSON string directly) would not agree with
 * the backend.
 *
 * Never log the keyset material or the pin (project hard rule).
 */
object KeysetPin {

    fun compute(publicKeysetJson: String): String {
        val handle = CleartextKeysetHandle.read(JsonKeysetReader.withString(publicKeysetJson))
        val binary = ByteArrayOutputStream().use { stream ->
            CleartextKeysetHandle.write(handle, BinaryKeysetWriter.withOutputStream(stream))
            stream.toByteArray()
        }
        val digest = MessageDigest.getInstance("SHA-256").digest(binary)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(digest)
    }
}
