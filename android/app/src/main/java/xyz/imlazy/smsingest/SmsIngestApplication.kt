package xyz.imlazy.smsingest

import android.app.Application
import android.content.ContentValues
import android.content.ContentUris
import android.provider.MediaStore
import java.io.PrintWriter
import java.io.StringWriter
import java.time.Instant

class SmsIngestApplication : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        installCrashLogger()
        container = AppContainer(this)
        // Idempotent (ExistingPeriodicWorkPolicy.KEEP) — safe to call on every start.
        container.syncScheduler.ensurePeriodicSync()
    }

    /**
     * Testing-phase-only: no adb/logcat access has been available on the
     * target device (`projects/sms-ingest/open-questions.md`), so an
     * uncaught crash otherwise leaves no readable trace. Writes the
     * exception (class, message, stack trace only — never SMS content or
     * key material) to a plain-text file in the public Downloads folder
     * via MediaStore, readable via any file manager without adb (unlike
     * the app's external-files dir under Android/data, which third-party
     * file managers can't browse into since Android 11's scoped-storage
     * lockdown). Then hands off to whatever crash handler was previously
     * installed so behavior is otherwise unchanged.
     */
    private fun installCrashLogger() {
        val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                val writer = StringWriter()
                throwable.printStackTrace(PrintWriter(writer))
                val text = "${Instant.now()}\n$writer"
                writeCrashLogToDownloads(text)
            } catch (_: Throwable) {
                // Best-effort only; never let logging itself block the real crash handling.
            }
            previousHandler?.uncaughtException(thread, throwable)
        }
    }

    private fun writeCrashLogToDownloads(text: String) {
        val resolver = contentResolver
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        // Delete any prior crash.txt first so repeated crashes overwrite rather than pile up.
        resolver.query(
            collection,
            arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME} = ?",
            arrayOf("crash.txt"),
            null,
        )?.use { cursor ->
            val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
            while (cursor.moveToNext()) {
                val id = cursor.getLong(idColumn)
                resolver.delete(ContentUris.withAppendedId(collection, id), null, null)
            }
        }
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, "crash.txt")
            put(MediaStore.Downloads.MIME_TYPE, "text/plain")
        }
        val uri = resolver.insert(collection, values) ?: return
        resolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
    }
}
