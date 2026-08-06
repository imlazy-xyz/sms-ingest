package xyz.imlazy.smsingest.debug

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import xyz.imlazy.smsingest.data.PendingBatchDao
import xyz.imlazy.smsingest.data.PendingBatchEntity
import xyz.imlazy.smsingest.data.UploadedDedupeDao
import xyz.imlazy.smsingest.sync.SyncScheduler

/**
 * Live testing-phase status for [SyncStatusScreen]: combines local queue
 * counts ([PendingBatchDao]/[UploadedDedupeDao]) with WorkManager's own
 * [SyncScheduler.observeWorkStates] so it's possible to tell, from the app
 * UI alone, whether SMS capture/sync is actually running — the gap noted in
 * `projects/sms-ingest/open-questions.md` ("no way to tell whether
 * backfill/sync had actually run" without querying the backend directly).
 */
class SyncStatusViewModel(
    pendingBatchDao: PendingBatchDao,
    uploadedDedupeDao: UploadedDedupeDao,
    private val syncScheduler: SyncScheduler,
) : ViewModel() {

    val uiState: StateFlow<SyncStatusUiState> = combine(
        pendingBatchDao.observeCountByState(PendingBatchEntity.STATE_PENDING),
        uploadedDedupeDao.observeCount(),
        pendingBatchDao.observeMostRecentStatus(),
        syncScheduler.observeWorkStates(),
    ) { pendingCount, uploadedCount, mostRecent, workStates ->
        SyncStatusUiState(
            pendingCount = pendingCount,
            uploadedCount = uploadedCount,
            lastAttemptAtEpochMillis = mostRecent?.updatedAtEpochMillis,
            lastAttemptState = mostRecent?.state,
            lastError = mostRecent?.lastError,
            lastRetryCount = mostRecent?.retryCount ?: 0,
            periodicSyncState = workStates[SyncScheduler.PERIODIC_WORK_NAME],
            expeditedSyncState = workStates[SyncScheduler.EXPEDITED_WORK_NAME],
            backfillState = workStates[SyncScheduler.BACKFILL_WORK_NAME],
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SyncStatusUiState())

    /** Manual "Sync now" — separates "nothing to sync" from "sync never triggered." */
    fun syncNow() = syncScheduler.requestExpeditedSync()

    /** Manual "Force backfill" — re-reads the whole inbox, bypassing the once-only guard. */
    fun forceBackfill() = syncScheduler.forceBackfill()

    companion object {
        fun factory(
            pendingBatchDao: PendingBatchDao,
            uploadedDedupeDao: UploadedDedupeDao,
            syncScheduler: SyncScheduler,
        ): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    SyncStatusViewModel(pendingBatchDao, uploadedDedupeDao, syncScheduler) as T
            }
    }
}
