package xyz.imlazy.smsingest.debug

import androidx.work.WorkInfo

/**
 * What the testing-phase debug view ([SyncStatusScreen]) needs to answer
 * "is anything happening" without a Supabase query: how many messages are
 * queued/uploaded, what the last sync attempt did, and whether WorkManager
 * is actually running the periodic/expedited/backfill workers at all — the
 * direct test of the OEM-background-restriction hypothesis in
 * `projects/sms-ingest/open-questions.md`.
 */
data class SyncStatusUiState(
    val pendingCount: Int = 0,
    val uploadedCount: Int = 0,
    val lastAttemptAtEpochMillis: Long? = null,
    val lastAttemptState: String? = null,
    val lastError: String? = null,
    val lastRetryCount: Int = 0,
    val periodicSyncState: WorkInfo.State? = null,
    val expeditedSyncState: WorkInfo.State? = null,
    val backfillState: WorkInfo.State? = null,
)

/** Short, human-readable label for a [WorkInfo.State]; `null` means never scheduled this app run. */
fun WorkInfo.State?.toStatusLabel(): String = when (this) {
    null -> "not scheduled"
    WorkInfo.State.ENQUEUED -> "queued"
    WorkInfo.State.RUNNING -> "running"
    WorkInfo.State.SUCCEEDED -> "succeeded"
    WorkInfo.State.FAILED -> "failed"
    WorkInfo.State.BLOCKED -> "blocked"
    WorkInfo.State.CANCELLED -> "cancelled"
}
