package xyz.imlazy.smsingest.sync

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.work.Configuration
import androidx.work.ListenableWorker
import androidx.work.Worker
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Exercises [SyncScheduler] against a real, synchronous, in-memory
 * [WorkManager] via the official androidx.work test harness
 * ([WorkManagerTestInitHelper]) rather than a mock, per
 * `docs/android-implementation-plan.md` Test Plan's "WorkManager scheduling"
 * coverage. [SynchronousExecutor] makes `enqueueUniqueWork`/
 * `enqueueUniquePeriodicWork` and the `getWorkInfosForUniqueWork(...).get()`
 * lookups below resolve synchronously — and, notably, *runs* any enqueued
 * work that has no unmet constraints and no initial delay. [SyncWorker]
 * requests are safe (they carry `NETWORK_CONSTRAINT`, so they stay
 * `ENQUEUED` since nothing here calls `setAllConstraintsMet`), but
 * [BackfillWorker] requests carry neither a constraint nor a delay, so the
 * default reflective factory would actually construct and run the real
 * `BackfillWorker` (touching `CredentialStore`/SMS `ContentResolver`/Room)
 * inside what's meant to be a scheduler-level test. [RetryingWorkerFactory]
 * below intercepts every worker class and substitutes a stub that returns
 * `Result.retry()`, so no real app `doWork()` ever executes here, and the
 * work spec stays non-finished (ENQUEUED with backoff) — the state
 * `KEEP`/`REPLACE` semantics are documented against.
 *
 * `@Config(application = ...)` substitutes the stock [android.app.Application]
 * for the manifest's `SmsIngestApplication`: Robolectric instantiates and
 * calls `onCreate()` on the manifest application *before* `@Before` runs,
 * and `SmsIngestApplication.onCreate()` unconditionally calls
 * `container.syncScheduler.ensurePeriodicSync()`, which calls
 * `WorkManager.getInstance(...)` before this class's `setUp()` has had a
 * chance to call `initializeTestWorkManager`. If WorkManager isn't already
 * initialized at that point (androidx.startup's auto-init provider is not
 * guaranteed to run in every Robolectric configuration), that throws
 * `IllegalStateException` and fails every test in this class during setup,
 * for a reason unrelated to what's under test. Swapping in a stock
 * `Application` also skips `AppContainer`'s eager Tink registration and
 * `SmsIngestApplication`'s `ActivityManager`/exit-reason lookups — none of
 * which this scheduler-level test needs.
 */
@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class SyncSchedulerTest {

    private lateinit var workManager: WorkManager
    private lateinit var scheduler: SyncScheduler

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val config = Configuration.Builder()
            .setExecutor(SynchronousExecutor())
            .setWorkerFactory(RetryingWorkerFactory())
            .build()
        WorkManagerTestInitHelper.initializeTestWorkManager(context, config)
        workManager = WorkManager.getInstance(context)
        scheduler = SyncScheduler(workManager)
    }

    /**
     * Stands in for every real worker class ([SyncWorker], [BackfillWorker])
     * so scheduler-level tests never execute real app `doWork()` logic.
     * `Result.retry()` (rather than `success()`) keeps the work spec
     * non-finished, matching what `ExistingWorkPolicy.KEEP` actually guards
     * against — a completed spec is not "existing work" to keep.
     */
    private class RetryingWorkerFactory : WorkerFactory() {
        override fun createWorker(
            appContext: Context,
            workerClassName: String,
            workerParameters: WorkerParameters,
        ): ListenableWorker = object : Worker(appContext, workerParameters) {
            override fun doWork(): Result = Result.retry()
        }
    }

    @Test
    fun `ensurePeriodicSync enqueues unique periodic work`() {
        scheduler.ensurePeriodicSync()

        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.PERIODIC_WORK_NAME).get()

        assertEquals(1, infos.size)
        assertEquals(WorkInfo.State.ENQUEUED, infos.single().state)
    }

    @Test
    fun `ensurePeriodicSync is idempotent under ExistingPeriodicWorkPolicy KEEP`() {
        scheduler.ensurePeriodicSync()
        val firstId = workManager.getWorkInfosForUniqueWork(SyncScheduler.PERIODIC_WORK_NAME).get().single().id

        scheduler.ensurePeriodicSync()
        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.PERIODIC_WORK_NAME).get()

        assertEquals(1, infos.size)
        assertEquals(firstId, infos.single().id)
    }

    @Test
    fun `requestExpeditedSync enqueues unique work`() {
        scheduler.requestExpeditedSync()

        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.EXPEDITED_WORK_NAME).get()

        assertEquals(1, infos.size)
    }

    @Test
    fun `requestExpeditedSync replaces the prior request under ExistingWorkPolicy REPLACE`() {
        scheduler.requestExpeditedSync()
        val firstId = workManager.getWorkInfosForUniqueWork(SyncScheduler.EXPEDITED_WORK_NAME).get().single().id

        scheduler.requestExpeditedSync()
        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.EXPEDITED_WORK_NAME).get()

        // Still exactly one WorkInfo for the unique name, not two, and it's a
        // different request than the one first enqueued.
        assertEquals(1, infos.size)
        assertNotEquals(firstId, infos.single().id)
    }

    @Test
    fun `enqueueBackfillIfNeeded enqueues unique work`() {
        scheduler.enqueueBackfillIfNeeded()

        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.BACKFILL_WORK_NAME).get()

        assertEquals(1, infos.size)
    }

    @Test
    fun `enqueueBackfillIfNeeded does not replace an already-enqueued backfill under ExistingWorkPolicy KEEP`() {
        scheduler.enqueueBackfillIfNeeded()
        val firstId = workManager.getWorkInfosForUniqueWork(SyncScheduler.BACKFILL_WORK_NAME).get().single().id

        scheduler.enqueueBackfillIfNeeded()
        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.BACKFILL_WORK_NAME).get()

        assertEquals(1, infos.size)
        assertEquals(firstId, infos.single().id)
    }

    @Test
    fun `forceBackfill enqueues unique work under the same name as enqueueBackfillIfNeeded`() {
        scheduler.forceBackfill()

        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.BACKFILL_WORK_NAME).get()

        assertEquals(1, infos.size)
    }

    @Test
    fun `forceBackfill replaces an already-enqueued backfill under ExistingWorkPolicy REPLACE`() {
        scheduler.enqueueBackfillIfNeeded()
        val firstId = workManager.getWorkInfosForUniqueWork(SyncScheduler.BACKFILL_WORK_NAME).get().single().id

        scheduler.forceBackfill()
        val infos = workManager.getWorkInfosForUniqueWork(SyncScheduler.BACKFILL_WORK_NAME).get()

        // forceBackfill uses REPLACE (unlike enqueueBackfillIfNeeded's KEEP),
        // so the pending request is swapped out rather than left in place.
        //
        // Note: this does not assert on the enqueued request's input data
        // (BackfillWorker.KEY_FORCE = true). WorkInfo, as returned by
        // getWorkInfosForUniqueWork, does not expose a pending request's
        // input Data in this project's pinned work:2.9.1 — WorkInfo only
        // surfaces *output* Data, and only once a worker has finished.
        // RetryingWorkerFactory (above) intentionally substitutes a stub
        // for the real BackfillWorker so this scheduler-level test never
        // touches CredentialStore/ContentResolver/Room, which forecloses
        // asserting KEY_FORCE was actually read. Asserting the replacement
        // happened (below) is as far as this test goes without fighting
        // that API; a future test that drives BackfillWorker itself (e.g.
        // via TestWorkerBuilder with a real WorkerFactory) would be the
        // place to assert KEY_FORCE took effect.
        assertEquals(1, infos.size)
        assertNotEquals(firstId, infos.single().id)
    }
}
