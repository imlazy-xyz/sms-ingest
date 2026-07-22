package xyz.imlazy.smsingest.crypto

import org.junit.Assert.assertEquals
import org.junit.Test

class ContextInfoTest {

    @Test
    fun sortsKeysRegardlessOfInputOrder() {
        val a = ContextInfo.canonicalString(linkedMapOf("b" to 2, "a" to 1))
        val b = ContextInfo.canonicalString(linkedMapOf("a" to 1, "b" to 2))
        assertEquals("""{"a":1,"b":2}""", a)
        assertEquals(a, b)
    }

    @Test
    fun formatsIntegersBare() {
        assertEquals("""{"version":1}""", ContextInfo.canonicalString(mapOf("version" to 1)))
    }

    @Test
    fun escapesJsonStringSpecials() {
        assertEquals(
            """{"k":"a\"b\\c\n"}""",
            ContextInfo.canonicalString(mapOf("k" to "a\"b\\c\n")),
        )
    }

    @Test
    fun keepsNonAsciiUnescaped() {
        // ensure_ascii=False: non-ASCII passes through as UTF-8, not \uXXXX.
        assertEquals("""{"k":"café"}""", ContextInfo.canonicalString(mapOf("k" to "café")))
    }
}
