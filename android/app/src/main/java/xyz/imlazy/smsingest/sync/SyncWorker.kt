package xyz.imlazy.smsingest.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import java.io.PrintWriter
import java.io.StringWriter
import java.time.Instant
import kotlinx.coroutines.CancellationException
import xyz.imlazy.smsingest.SmsIngestApplication
import xyz.imlazy.smsingest.debug.DownloadsFileLog

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
        // Testing-phase-only: WorkManager already converts an uncaught doWork()
        // exception into Result.failure() on its own, but it never surfaces that
        // exception to the app's uncaught-exception handler (SmsIngestApplication),
        // so without adb it would otherwise leave no trace at all — see
        // projects/sms-ingest/open-questions.md.
        val syncResult = try {
            syncer.sync()
        } catch (cancellation: CancellationException) {
            throw cancellation
        } catch (throwable: Throwable) {
            logSyncError(throwable)
            return Result.failure()
        }
        Log.d(TAG, "doWork: $syncResult")
        return when (syncResult) {
            SyncResult.SUCCESS, SyncResult.NOT_PROVISIONED -> Result.success()
            SyncResult.RETRY -> Result.retry()
        }
    }

    private fun logSyncError(throwable: Throwable) {
        try {
            val writer = StringWriter()
            throwable.printStackTrace(PrintWriter(writer))
            DownloadsFileLog.write(applicationContext, "sync_error.txt", "${Instant.now()}\n$writer")
        } catch (_: Throwable) {
            // Best-effort only.
        }
    }

    private companion object {
        const val TAG = "SyncWorker"
    }
}
