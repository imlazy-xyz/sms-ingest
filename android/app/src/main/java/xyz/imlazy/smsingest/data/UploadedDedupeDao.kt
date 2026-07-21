package xyz.imlazy.smsingest.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface UploadedDedupeDao {

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(entry: UploadedDedupeIdEntity)

    @Query("SELECT EXISTS(SELECT 1 FROM uploaded_dedupe_ids WHERE dedupeId = :dedupeId)")
    suspend fun exists(dedupeId: String): Boolean
}
