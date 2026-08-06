package xyz.imlazy.smsingest.data

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface PendingBatchDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(batch: PendingBatchEntity)

    @Update
    suspend fun update(batch: PendingBatchEntity)

    @Delete
    suspend fun delete(batch: PendingBatchEntity)

    @Query("SELECT * FROM pending_batches WHERE clientBatchId = :clientBatchId")
    suspend fun getByClientBatchId(clientBatchId: String): PendingBatchEntity?

    @Query("SELECT * FROM pending_batches WHERE state = :state ORDER BY createdAtEpochMillis ASC")
    fun observeByState(state: String): Flow<List<PendingBatchEntity>>

    /** One-shot read for [xyz.imlazy.smsingest.sync.BatchSyncer], which processes a batch and moves on. */
    @Query("SELECT * FROM pending_batches WHERE state = :state ORDER BY createdAtEpochMillis ASC")
    suspend fun getByState(state: String): List<PendingBatchEntity>

    /**
     * Deletes any row whose `messagesJson` is large enough to risk exceeding
     * Android's per-row CursorWindow limit when [getByState] reads it back
     * (`SQLiteBlobTooBigException`). Self-healing cleanup for pre-chunking
     * rows: before [xyz.imlazy.smsingest.sms.SmsIngestor] split backfill into
     * size-bounded batches, one un-chunked batch could hold the whole inbox
     * in a single row and permanently crash every `SELECT *` on the table —
     * including [getByState] and [getByClientBatchId], so the row can't even
     * be read out one at a time to fix in place. `DELETE` never materializes
     * the blob into a CursorWindow, so it succeeds where those throw.
     *
     * `length()` counts characters, not bytes; the caller's threshold stays
     * well below the ~2MB byte limit to leave margin for multi-byte bodies,
     * and well above any batch [SmsIngestor] now produces so it never deletes
     * a validly-chunked row. Returns the number of rows deleted.
     */
    @Query("DELETE FROM pending_batches WHERE length(messagesJson) > :maxChars")
    suspend fun deleteOversized(maxChars: Int): Int

    /**
     * Row count only, for [xyz.imlazy.smsingest.debug.SyncStatusViewModel]'s
     * pending-count display. Deliberately not [observeByState]: a backfill
     * batch's `messagesJson` (the whole queued-SMS JSON blob) can exceed
     * Android's per-row CursorWindow limit (`SQLiteBlobTooBigException`),
     * and the UI only ever needed the count, never the rows.
     */
    @Query("SELECT COUNT(*) FROM pending_batches WHERE state = :state")
    fun observeCountByState(state: String): Flow<Int>

    /**
     * Most recently touched batch across all states, for
     * [xyz.imlazy.smsingest.debug.SyncStatusViewModel] to surface "last sync
     * attempt" (timestamp/state/error/retry count) without caring whether
     * that attempt ended up sent or still pending. Projects out
     * `messagesJson` for the same CursorWindow-size reason as
     * [observeCountByState] — the UI never reads the message payload.
     */
    @Query(
        "SELECT state, updatedAtEpochMillis, retryCount, lastError FROM pending_batches " +
            "ORDER BY updatedAtEpochMillis DESC LIMIT 1",
    )
    fun observeMostRecentStatus(): Flow<PendingBatchStatus?>
}

/** Lightweight projection of [PendingBatchEntity] excluding `messagesJson`. */
data class PendingBatchStatus(
    val state: String,
    val updatedAtEpochMillis: Long,
    val retryCount: Int,
    val lastError: String?,
)
