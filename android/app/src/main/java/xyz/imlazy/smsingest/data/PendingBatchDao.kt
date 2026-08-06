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
     * Most recently touched batch across all states, for
     * [xyz.imlazy.smsingest.debug.SyncStatusViewModel] to surface "last sync
     * attempt" (timestamp/state/error/retry count) without caring whether
     * that attempt ended up sent or still pending.
     */
    @Query("SELECT * FROM pending_batches ORDER BY updatedAtEpochMillis DESC LIMIT 1")
    fun observeMostRecent(): Flow<PendingBatchEntity?>
}
