package xyz.imlazy.smsingest.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import xyz.imlazy.smsingest.SmsIngestApplication

/**
 * WorkManager entry point for [BatchSyncer]: pulls dependencies from
 * [xyz.imlazy.smsingest.AppContainer] at run time (same pattern as
 * [xyz.imlazy.smsingest.sms.SmsReceiver], since WorkManager instantiates
 * workers via reflection — no constructor injection). Kept thin; the
 * testable upload/retry logic lives in [BatchSyncer].
 *
 * Scheduled by [SyncScheduler] as both a periodic reconciliation worker and
 * an expedited one-time worker (`docs/android-implementation-plan.md`
 * Phase 7); both share this same class so retry logic isn't duplicated.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as SmsIngestApplication).container
        val syncer = BatchSyncer(
            pendingBatchDao = container.database.pendingBatchDao(),
            uploadedDedupeDao = container.database.uploadedDedupeDao(),
            credentialStore = container.credentialStore,
            ingestApiProvider = container::createIngestApiOrNull,
            deviceInfoProvider = container.deviceInfoProvider,
        )
        return when (syncer.sync()) {
            SyncResult.SUCCESS, SyncResult.NOT_PROVISIONED -> Result.success()
            SyncResult.RETRY -> Result.retry()
        }
    }
}
