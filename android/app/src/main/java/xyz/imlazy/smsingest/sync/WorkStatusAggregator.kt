package xyz.imlazy.smsingest.sync

import androidx.work.WorkInfo

/**
 * WorkManager keeps finished [WorkInfo] rows around (until pruned) alongside
 * any freshly (re-)enqueued one for the same unique work name, and exposes
 * no timestamp to pick the "current" entry by recency. Reducing the whole
 * list to a single most-useful state is done by priority instead: an
 * in-flight state always wins over a stale terminal one, and among terminal
 * states a failure is surfaced ahead of an old success.
 *
 * Pure/no Android runtime dependency beyond the [WorkInfo.State] enum
 * itself, so this is unit-testable without Robolectric/an emulator — used by
 * [xyz.imlazy.smsingest.debug.SyncStatusViewModel] to summarize
 * `getWorkInfosForUniqueWorkFlow` results for the periodic/expedited/backfill
 * unique work names.
 */
object WorkStatusAggregator {

    private val PRIORITY = listOf(
        WorkInfo.State.RUNNING,
        WorkInfo.State.ENQUEUED,
        WorkInfo.State.BLOCKED,
        WorkInfo.State.FAILED,
        WorkInfo.State.SUCCEEDED,
        WorkInfo.State.CANCELLED,
    )

    fun aggregate(states: List<WorkInfo.State>): WorkInfo.State? = PRIORITY.firstOrNull { it in states }
}
