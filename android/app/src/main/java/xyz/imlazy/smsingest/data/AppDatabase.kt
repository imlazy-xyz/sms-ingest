package xyz.imlazy.smsingest.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [PendingBatchEntity::class, UploadedDedupeIdEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {

    abstract fun pendingBatchDao(): PendingBatchDao

    abstract fun uploadedDedupeDao(): UploadedDedupeDao

    companion object {
        private const val DB_NAME = "sms-ingest.db"

        fun build(context: Context): AppDatabase =
            Room.databaseBuilder(context.applicationContext, AppDatabase::class.java, DB_NAME)
                .build()
    }
}
