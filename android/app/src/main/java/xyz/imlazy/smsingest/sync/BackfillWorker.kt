package xyz.imlazy.smsingest.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import xyz.imlazy.smsingest.SmsIngestApplication
import xyz.imlazy.smsingest.sms.SmsBackfillReader

/**
 * One-time historical inbox backfill. Enqueued once, right after setup
 * completes ([SyncScheduler.enqueueBackfillIfNeeded], triggered from
 * [xyz.imlazy.smsingest.setup.SetupViewModel]'s `onProvisioned` callback) —
 * this was left unwired in Phase 6
 * (`projects/sms-ingest/docs/android-implementation-plan.md` Phase 7 note).
 *
 * Guarded by [xyz.imlazy.smsingest.setup.CredentialStore.isBackfillComplete]
 * so a re-enqueue (WorkManager's own unique-work "already ran" record can be
 * pruned over time) is a fast no-op rather than a repeat read of the whole
 * inbox.
 *
 * Not unit-testable in this repo, same as [SmsBackfillReader] itself
 * (`ContentResolver` needs an instrumented test/emulator) — kept thin so
 * manual review can cover it.
 */
class BackfillWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as SmsIngestApplication).container
        val credentialStore = container.credentialStore
        if (credentialStore.isBackfillComplete() || !credentialStore.isProvisioned()) {
            return Result.success()
        }
        val captures = SmsBackfillReader(applicationContext).read()
        container.smsIngestor.enqueue(captures)
        credentialStore.markBackfillComplete()
        return Result.success()
    }
}
