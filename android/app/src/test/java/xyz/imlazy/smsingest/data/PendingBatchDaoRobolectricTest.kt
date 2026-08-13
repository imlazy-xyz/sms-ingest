package xyz.imlazy.smsingest.data

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Exercises [PendingBatchDao] against a real in-memory Room database (not a
 * mock/fake), closing the plan's "Room DAO behavior" test-plan gap. The
 * `deleteOversized` tests below are a regression test for the production
 * `SQLiteBlobTooBigException` crash described on
 * [PendingBatchDao.deleteOversized]'s doc comment.
 *
 * `@Config(application = ...)` substitutes the stock [android.app.Application]
 * for the manifest's [xyz.imlazy.smsingest.SmsIngestApplication], which
 * Robolectric would otherwise instantiate and run `onCreate()` on before
 * `@Before` — that real `onCreate()` builds a full `AppContainer` and forces
 * `SyncScheduler.ensurePeriodicSync()` (`WorkManager.getInstance(...)`) with
 * no test-WorkManager init, work this test has no reason to trigger. See
 * `SyncSchedulerTest`'s class doc for the concrete crash this avoids.
 */
@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class PendingBatchDaoRobolectricTest {

    private lateinit var db: AppDatabase
    private lateinit var dao: PendingBatchDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), AppDatabase::class.java)
            .build()
        dao = db.pendingBatchDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    private fun batch(
        clientBatchId: String,
        messagesJson: String = "[]",
        state: String = PendingBatchEntity.STATE_PENDING,
        createdAtEpochMillis: Long = 1_000,
        updatedAtEpochMillis: Long = 1_000,
        retryCount: Int = 0,
        lastError: String? = null,
    ) = PendingBatchEntity(
        clientBatchId = clientBatchId,
        messagesJson = messagesJson,
        state = state,
        createdAtEpochMillis = createdAtEpochMillis,
        updatedAtEpochMillis = updatedAtEpochMillis,
        retryCount = retryCount,
        lastError = lastError,
    )

    @Test
    fun `insert then getByClientBatchId round-trips the row`() = runTest {
        dao.insert(batch("b1", messagesJson = """[{"id":"m1"}]"""))

        val loaded = dao.getByClientBatchId("b1")

        assertEquals("b1", loaded?.clientBatchId)
        assertEquals("""[{"id":"m1"}]""", loaded?.messagesJson)
        assertEquals(PendingBatchEntity.STATE_PENDING, loaded?.state)
    }

    @Test
    fun `update mutates the same row`() = runTest {
        dao.insert(batch("b1", state = PendingBatchEntity.STATE_PENDING, retryCount = 0))

        val existing = dao.getByClientBatchId("b1")!!
        dao.update(existing.copy(state = PendingBatchEntity.STATE_SENT, retryCount = 3, lastError = "http_500"))

        val loaded = dao.getByClientBatchId("b1")
        assertEquals(PendingBatchEntity.STATE_SENT, loaded?.state)
        assertEquals(3, loaded?.retryCount)
        assertEquals("http_500", loaded?.lastError)
    }

    @Test
    fun `delete removes the row`() = runTest {
        dao.insert(batch("b1"))

        dao.delete(dao.getByClientBatchId("b1")!!)

        assertNull(dao.getByClientBatchId("b1"))
    }

    @Test
    fun `getByState returns only matching rows ordered by createdAtEpochMillis ascending`() = runTest {
        dao.insert(batch("b3", state = PendingBatchEntity.STATE_PENDING, createdAtEpochMillis = 3_000))
        dao.insert(batch("b1", state = PendingBatchEntity.STATE_PENDING, createdAtEpochMillis = 1_000))
        dao.insert(batch("sent", state = PendingBatchEntity.STATE_SENT, createdAtEpochMillis = 500))
        dao.insert(batch("b2", state = PendingBatchEntity.STATE_PENDING, createdAtEpochMillis = 2_000))

        val pending = dao.getByState(PendingBatchEntity.STATE_PENDING)

        assertEquals(listOf("b1", "b2", "b3"), pending.map { it.clientBatchId })
    }

    @Test
    fun `observeByState returns only matching rows ordered by createdAtEpochMillis ascending`() = runTest {
        dao.insert(batch("b3", state = PendingBatchEntity.STATE_PENDING, createdAtEpochMillis = 3_000))
        dao.insert(batch("b1", state = PendingBatchEntity.STATE_PENDING, createdAtEpochMillis = 1_000))
        dao.insert(batch("sent", state = PendingBatchEntity.STATE_SENT, createdAtEpochMillis = 500))
        dao.insert(batch("b2", state = PendingBatchEntity.STATE_PENDING, createdAtEpochMillis = 2_000))

        val pending = dao.observeByState(PendingBatchEntity.STATE_PENDING).first()

        assertEquals(listOf("b1", "b2", "b3"), pending.map { it.clientBatchId })
    }

    @Test
    fun `deleteOversized deletes rows past the char threshold and leaves smaller rows untouched`() = runTest {
        val oversized = "x".repeat(1_000)
        val small = "x".repeat(10)
        dao.insert(batch("big", messagesJson = oversized))
        dao.insert(batch("small", messagesJson = small))

        val deletedCount = dao.deleteOversized(maxChars = 100)

        assertEquals(1, deletedCount)
        assertNull("oversized row must be purged", dao.getByClientBatchId("big"))
        assertEquals("small row must survive", small, dao.getByClientBatchId("small")?.messagesJson)
    }

    @Test
    fun `deleteOversized is a no-op when no row exceeds the threshold`() = runTest {
        dao.insert(batch("b1", messagesJson = "x".repeat(10)))
        dao.insert(batch("b2", messagesJson = "x".repeat(20)))

        val deletedCount = dao.deleteOversized(maxChars = 100)

        assertEquals(0, deletedCount)
        assertTrue(dao.getByClientBatchId("b1") != null && dao.getByClientBatchId("b2") != null)
    }

    @Test
    fun `observeCountByState reflects insert and delete changes`() = runTest {
        assertEquals(0, dao.observeCountByState(PendingBatchEntity.STATE_PENDING).first())

        dao.insert(batch("b1"))
        dao.insert(batch("b2"))
        assertEquals(2, dao.observeCountByState(PendingBatchEntity.STATE_PENDING).first())

        dao.delete(dao.getByClientBatchId("b1")!!)
        assertEquals(1, dao.observeCountByState(PendingBatchEntity.STATE_PENDING).first())
    }

    @Test
    fun `observeCountByState only counts rows in the given state`() = runTest {
        dao.insert(batch("b1", state = PendingBatchEntity.STATE_PENDING))
        dao.insert(batch("b2", state = PendingBatchEntity.STATE_SENT))

        assertEquals(1, dao.observeCountByState(PendingBatchEntity.STATE_PENDING).first())
        assertEquals(1, dao.observeCountByState(PendingBatchEntity.STATE_SENT).first())
    }

    @Test
    fun `observeMostRecentStatus returns the projection of the most recently updated row`() = runTest {
        dao.insert(
            batch(
                "older",
                state = PendingBatchEntity.STATE_SENT,
                updatedAtEpochMillis = 1_000,
                retryCount = 0,
                lastError = null,
            ),
        )
        dao.insert(
            batch(
                "newer",
                state = PendingBatchEntity.STATE_PENDING,
                updatedAtEpochMillis = 2_000,
                retryCount = 2,
                lastError = "http_500",
            ),
        )

        val status = dao.observeMostRecentStatus().first()

        assertEquals(PendingBatchEntity.STATE_PENDING, status?.state)
        assertEquals(2_000L, status?.updatedAtEpochMillis)
        assertEquals(2, status?.retryCount)
        assertEquals("http_500", status?.lastError)
    }

    @Test
    fun `observeMostRecentStatus updates when a newer row is inserted`() = runTest {
        dao.insert(batch("b1", updatedAtEpochMillis = 1_000, state = PendingBatchEntity.STATE_PENDING))
        assertEquals(PendingBatchEntity.STATE_PENDING, dao.observeMostRecentStatus().first()?.state)

        dao.insert(batch("b2", updatedAtEpochMillis = 5_000, state = PendingBatchEntity.STATE_SENT))

        val status = dao.observeMostRecentStatus().first()
        assertEquals(PendingBatchEntity.STATE_SENT, status?.state)
        assertEquals(5_000L, status?.updatedAtEpochMillis)
    }
}
