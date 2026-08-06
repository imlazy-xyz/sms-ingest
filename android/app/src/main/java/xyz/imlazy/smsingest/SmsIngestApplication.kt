package xyz.imlazy.smsingest

import android.app.Application
import java.io.File
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
     * key material) to a plain-text file under the app's external files
     * dir, readable via any file manager without adb, then hands off to
     * whatever crash handler was previously installed so behavior is
     * otherwise unchanged.
     */
    private fun installCrashLogger() {
        val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                val writer = StringWriter()
                throwable.printStackTrace(PrintWriter(writer))
                val file = File(getExternalFilesDir(null), "crash.txt")
                file.writeText("${Instant.now()}\n$writer")
            } catch (_: Throwable) {
                // Best-effort only; never let logging itself block the real crash handling.
            }
            previousHandler?.uncaughtException(thread, throwable)
        }
    }
}
