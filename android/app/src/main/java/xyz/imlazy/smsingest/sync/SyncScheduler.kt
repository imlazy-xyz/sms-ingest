package xyz.imlazy.smsingest.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequest
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkRequest
import java.util.concurrent.TimeUnit

/**
 * Schedules [SyncWorker]/[BackfillWorker] via WorkManager, per
 * `docs/android-implementation-plan.md` Phase 7 and `decisions.md`
 * 2026-07-21 ("one periodic worker plus an expedited one-time enqueue from
 * the SMS receiver, both funneling into the same upload/retry path"):
 *
 * - [ensurePeriodicSync]: reconciliation, any-network, exponential backoff.
 * - [requestExpeditedSync]: near-real-time upload after new SMS.
 * - [enqueueBackfillIfNeeded]: one-time historical inbox read, separate from
 *   the upload path since it only queues locally (no network needed).
 */
class SyncScheduler(private val workManager: WorkManager) {

    constructor(context: Context) : this(WorkManager.getInstance(context.applicationContext))

    /** Idempotent: safe to call on every app start (`ExistingPeriodicWorkPolicy.KEEP`). */
    fun ensurePeriodicSync() {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(
            PeriodicWorkRequest.MIN_PERIODIC_INTERVAL_MILLIS,
            TimeUnit.MILLISECONDS,
        )
            .setConstraints(NETWORK_CONSTRAINT)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, WorkRequest.MIN_BACKOFF_MILLIS, TimeUnit.MILLISECONDS)
            .build()
        workManager.enqueueUniquePeriodicWork(PERIODIC_WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    /**
     * Near-real-time upload after a new SMS arrives
     * ([xyz.imlazy.smsingest.sms.SmsReceiver]). `RUN_AS_NON_EXPEDITED_WORK_REQUEST`
     * falls back to a regular request under quota pressure instead of
     * requiring a foreground-service permission.
     */
    fun requestExpeditedSync() {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .setConstraints(NETWORK_CONSTRAINT)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, WorkRequest.MIN_BACKOFF_MILLIS, TimeUnit.MILLISECONDS)
            .build()
        workManager.enqueueUniqueWork(EXPEDITED_WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }

    /**
     * Enqueues the one-time historical inbox backfill. Called once, right
     * after setup completes ([xyz.imlazy.smsingest.setup.SetupViewModel]'s
     * `onProvisioned` callback). [BackfillWorker] itself is idempotent
     * ([xyz.imlazy.smsingest.setup.CredentialStore.isBackfillComplete]), so
     * `KEEP` here is only a cheap first line of defense, not the source of
     * truth for "run at most once."
     */
    fun enqueueBackfillIfNeeded() {
        val request = OneTimeWorkRequestBuilder<BackfillWorker>().build()
        workManager.enqueueUniqueWork(BACKFILL_WORK_NAME, ExistingWorkPolicy.KEEP, request)
    }

    private companion object {
        const val PERIODIC_WORK_NAME = "sms-sync-periodic"
        const val EXPEDITED_WORK_NAME = "sms-sync-expedited"
        const val BACKFILL_WORK_NAME = "sms-backfill-once"

        val NETWORK_CONSTRAINT: Constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
    }
}
