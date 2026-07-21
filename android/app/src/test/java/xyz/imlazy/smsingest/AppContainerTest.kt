package xyz.imlazy.smsingest

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Placeholder for the Phase 1 scaffold. Real coverage (dedupe canonicalization,
 * QR payload parsing, crypto round-trip) lands with the phases that add that code
 * — see projects/sms-ingest/docs/android-implementation-plan.md § Test Plan.
 */
class AppContainerTest {

    @Test
    fun `package name matches the locked applicationId decision`() {
        assertEquals("xyz.imlazy.smsingest", AppContainer::class.java.`package`?.name)
    }
}
