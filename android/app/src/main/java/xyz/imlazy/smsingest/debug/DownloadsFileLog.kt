package xyz.imlazy.smsingest.debug

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.provider.MediaStore

/**
 * Testing-phase-only: no adb/logcat access has been available on the target
 * device (`projects/sms-ingest/open-questions.md`), so anything that would
 * otherwise only show up in logcat is instead written as a plain-text file
 * in the public Downloads folder via MediaStore, readable via any file
 * manager without adb (unlike the app's external-files dir under
 * Android/data, which third-party file managers can't browse into since
 * Android 11's scoped-storage lockdown).
 */
object DownloadsFileLog {
    /** Subfolder under Downloads all debug files land in, so they're grouped together and easy to find. */
    private const val RELATIVE_PATH = "Download/sms-ingest-debug/"

    fun write(context: Context, fileName: String, text: String) {
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        // Delete any prior file with the same name+folder first so repeated runs overwrite rather than pile up.
        resolver.query(
            collection,
            arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME} = ? AND ${MediaStore.Downloads.RELATIVE_PATH} = ?",
            arrayOf(fileName, RELATIVE_PATH),
            null,
        )?.use { cursor ->
            val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
            while (cursor.moveToNext()) {
                val id = cursor.getLong(idColumn)
                resolver.delete(ContentUris.withAppendedId(collection, id), null, null)
            }
        }
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.MIME_TYPE, "text/plain")
            put(MediaStore.Downloads.RELATIVE_PATH, RELATIVE_PATH)
        }
        val uri = resolver.insert(collection, values) ?: return
        resolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
    }
}
