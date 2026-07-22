package xyz.imlazy.smsingest.crypto

import java.nio.charset.StandardCharsets

/**
 * Canonical byte encoding of the HPKE `context_info` (the bound public request
 * metadata). Must reproduce the backend's bytes exactly, per
 * `backend/app/core/crypto.py::canonical_context_info`:
 *
 *     json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
 *         .encode("utf-8")
 *
 * i.e. compact JSON (no whitespace), keys sorted by Unicode code point, no
 * ASCII-escaping of non-ASCII characters. This is a byte-for-byte contract: if
 * the encrypt-side bytes differ from the decrypt-side bytes by even one byte,
 * HPKE decryption fails. Built by hand rather than delegating to a
 * general-purpose serializer, whose default settings are not guaranteed to
 * match Python's dump options for every value type.
 *
 * Values are limited to the types the wire contract uses: JSON strings and
 * integers. Passing any other type is a programming error.
 */
object ContextInfo {

    /**
     * @param fields context_info key/value pairs. Keys are sorted here, so the
     *   caller may pass them in any order.
     */
    fun canonicalBytes(fields: Map<String, Any>): ByteArray =
        canonicalString(fields).toByteArray(StandardCharsets.UTF_8)

    fun canonicalString(fields: Map<String, Any>): String = buildString {
        append('{')
        fields.entries
            .sortedBy { it.key }
            .forEachIndexed { index, (key, value) ->
                if (index > 0) append(',')
                appendJsonString(key)
                append(':')
                appendJsonValue(value)
            }
        append('}')
    }

    private fun StringBuilder.appendJsonValue(value: Any) {
        when (value) {
            is String -> appendJsonString(value)
            // Match Python's bare integer formatting (`1`, not `1.0`/`"1"`).
            is Int -> append(value.toString())
            is Long -> append(value.toString())
            else -> throw IllegalArgumentException(
                "unsupported context_info value type: ${value::class.java.name}",
            )
        }
    }

    /** Emit a JSON string with the same escaping `json.dumps(..., ensure_ascii=False)` uses. */
    private fun StringBuilder.appendJsonString(value: String) {
        append('"')
        for (ch in value) {
            when (ch) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                '\b' -> append("\\b")
                '\u000C' -> append("\\f")
                else ->
                    if (ch < ' ') {
                        append("\\u").append(ch.code.toString(16).padStart(4, '0'))
                    } else {
                        append(ch)
                    }
            }
        }
        append('"')
    }
}
