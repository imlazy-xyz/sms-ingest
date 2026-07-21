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
}
