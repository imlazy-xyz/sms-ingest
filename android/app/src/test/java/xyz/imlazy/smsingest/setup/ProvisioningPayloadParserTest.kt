package xyz.imlazy.smsingest.setup

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProvisioningPayloadParserTest {

    // 32 zero bytes, base64url-nopad-encoded — a structurally valid (not real) key pin.
    private val validPin = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    private fun validJson(overrides: Map<String, String> = emptyMap()): String {
        val fields = linkedMapOf(
            "v" to "1",
            "api_base_url" to "\"https://sms-api.example.com\"",
            "device_id" to "\"11111111-1111-1111-1111-111111111111\"",
            "device_token" to "\"raw-token\"",
            "device_dedupe_secret" to "\"raw-secret\"",
            "server_key_id" to "\"server-key-2026-05\"",
            "server_key_pin" to "\"$validPin\"",
            "issued_at" to "\"2026-05-23T00:00:00Z\"",
        )
        overrides.forEach { (key, value) -> fields[key] = value }
        return fields.entries.joinToString(prefix = "{", postfix = "}") { (k, v) -> "\"$k\":$v" }
    }

    @Test
    fun `parses a well-formed payload`() {
        val result = ProvisioningPayloadParser.parse(validJson())

        assertTrue(result.isSuccess)
        val payload = result.getOrThrow()
        assertEquals(1, payload.v)
        assertEquals("https://sms-api.example.com", payload.apiBaseUrl)
        assertEquals(validPin, payload.serverKeyPin)
    }

    @Test
    fun `rejects malformed JSON`() {
        val result = ProvisioningPayloadParser.parse("not json")

        assertTrue(result.isFailure)
    }

    @Test
    fun `rejects an unsupported version`() {
        val result = ProvisioningPayloadParser.parse(validJson(mapOf("v" to "2")))

        assertTrue(result.isFailure)
    }

    @Test
    fun `rejects a missing required field`() {
        val result = ProvisioningPayloadParser.parse(validJson(mapOf("device_token" to "\"\"")))

        assertTrue(result.isFailure)
    }

    @Test
    fun `rejects a non-https api_base_url`() {
        val result = ProvisioningPayloadParser.parse(
            validJson(mapOf("api_base_url" to "\"http://sms-api.example.com\"")),
        )

        assertTrue(result.isFailure)
    }

    @Test
    fun `rejects a server_key_pin that does not decode to a 32-byte digest`() {
        val result = ProvisioningPayloadParser.parse(
            validJson(mapOf("server_key_pin" to "\"not-a-real-fingerprint\"")),
        )

        assertTrue(result.isFailure)
    }

    @Test
    fun `ignores unknown fields for forward compatibility`() {
        val json = validJson().dropLast(1) + ",\"future_field\":\"x\"}"

        val result = ProvisioningPayloadParser.parse(json)

        assertTrue(result.isSuccess)
    }
}
