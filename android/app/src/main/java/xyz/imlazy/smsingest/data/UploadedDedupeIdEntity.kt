package xyz.imlazy.smsingest.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Already-uploaded dedupe fingerprints, kept on-device so a re-scan of the
 * SMS inbox (backfill, or a receiver re-trigger) can be suppressed locally
 * before ever hitting the network.
 */
@Entity(tableName = "uploaded_dedupe_ids")
data class UploadedDedupeIdEntity(
    @PrimaryKey val dedupeId: String,
    val uploadedAtEpochMillis: Long,
)
