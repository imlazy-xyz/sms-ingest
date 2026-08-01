package xyz.imlazy.smsingest.sync

import xyz.imlazy.smsingest.setup.CredentialStore

/**
 * Whether [BackfillWorker] should actually read the inbox this run: only
 * once, and only once the device is provisioned. Split out from the worker
 * (which needs a `Context` for
 * [xyz.imlazy.smsingest.sms.SmsBackfillReader]) purely so this small but
 * easy-to-get-wrong guard is unit-testable.
 */
object BackfillGate {
    fun shouldRun(credentialStore: CredentialStore): Boolean =
        credentialStore.isProvisioned() && !credentialStore.isBackfillComplete()
}
