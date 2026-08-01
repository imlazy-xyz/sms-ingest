package xyz.imlazy.smsingest.sync

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import xyz.imlazy.smsingest.setup.CredentialStore
import xyz.imlazy.smsingest.setup.ProvisioningPayload

// Named distinctly from sync/BatchSyncerTest.kt's own `FakeCredentialStore`:
// both are `private`, but a top-level `private` class in Kotlin is only
// file-*visibility*-scoped, not name-mangled — two files in the same package
// declaring the same class name is a real compile-time redeclaration clash,
// not just a style nit (caught by CI: cascaded into spurious "unresolved
// reference" errors throughout BatchSyncerTest.kt too).
private class FakeGateCredentialStore(
    private val provisioned: Boolean,
    private val backfillComplete: Boolean,
) : CredentialStore {
    override fun isProvisioned(): Boolean = provisioned
    override fun save(payload: ProvisioningPayload, publicKeysetJson: String) = Unit
    override fun getApiBaseUrl(): String? = null
    override fun getServerKeyId(): String? = null
    override fun getServerKeyPin(): String? = null
    override fun getPublicKeysetJson(): String? = null
    override fun getDeviceToken(): String? = null
    override fun getDeviceDedupeSecret(): String? = null
    override fun isBackfillComplete(): Boolean = backfillComplete
    override fun markBackfillComplete() = Unit
}

class BackfillGateTest {

    @Test
    fun `runs when provisioned and backfill has not completed`() {
        assertTrue(BackfillGate.shouldRun(FakeGateCredentialStore(provisioned = true, backfillComplete = false)))
    }

    @Test
    fun `does not run when not yet provisioned`() {
        assertFalse(BackfillGate.shouldRun(FakeGateCredentialStore(provisioned = false, backfillComplete = false)))
    }

    @Test
    fun `does not run again once backfill has already completed`() {
        assertFalse(BackfillGate.shouldRun(FakeGateCredentialStore(provisioned = true, backfillComplete = true)))
    }
}
