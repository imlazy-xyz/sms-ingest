package xyz.imlazy.smsingest

import android.app.ActivityManager
import android.app.Application
import android.app.ApplicationExitInfo
import java.io.PrintWriter
import java.io.StringWriter
import java.time.Instant
import xyz.imlazy.smsingest.debug.DownloadsFileLog

class SmsIngestApplication : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        installCrashLogger()
        dumpLastExitReasonIfAbnormal()
        container = AppContainer(this)
        // Idempotent (ExistingPeriodicWorkPolicy.KEEP) — safe to call on every start.
        container.syncScheduler.ensurePeriodicSync()
    }

    /**
     * Testing-phase-only: covers the case the uncaught-exception handler
     * below can't — a silent app disappearance with no crash dialog is
     * usually an ANR or the OS/OEM killing the process outright, neither
     * of which ever reaches a Java exception handler. On the next launch,
     * ask the platform why the previous process actually died
     * (`ActivityManager.getHistoricalProcessExitReasons`, API 30+) and, if
     * it wasn't a normal exit, write the reason/description and any
     * available trace to the public Downloads folder.
     */
    private fun dumpLastExitReasonIfAbnormal() {
        try {
            val am = getSystemService(ActivityManager::class.java) ?: return
            val reasons = am.getHistoricalProcessExitReasons(packageName, 0, 5)
            val abnormal = reasons.filter {
                it.reason != ApplicationExitInfo.REASON_USER_REQUESTED &&
                    it.reason != ApplicationExitInfo.REASON_USER_STOPPED
            }
            if (abnormal.isEmpty()) return
            val text = buildString {
                for (info in abnormal) {
                    appendLine("timestamp=${Instant.ofEpochMilli(info.timestamp)}")
                    appendLine("reason=${info.reason} (${reasonName(info.reason)})")
                    appendLine("status=${info.status}")
                    appendLine("importance=${info.importance}")
                    appendLine("description=${info.description}")
                    try {
                        info.traceInputStream?.use { stream ->
                            appendLine("trace:")
                            appendLine(stream.readBytes().toString(Charsets.UTF_8))
                        }
                    } catch (_: Throwable) {
                        // Trace not always available (e.g. plain kills); reason/description alone is still useful.
                    }
                    appendLine("---")
                }
            }
            DownloadsFileLog.write(this, "exit_reason.txt", text)
        } catch (_: Throwable) {
            // Best-effort only.
        }
    }

    private fun reasonName(reason: Int): String = when (reason) {
        ApplicationExitInfo.REASON_ANR -> "ANR"
        ApplicationExitInfo.REASON_CRASH -> "CRASH"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "CRASH_NATIVE"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "LOW_MEMORY"
        ApplicationExitInfo.REASON_SIGNALED -> "SIGNALED"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "PERMISSION_CHANGE"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "EXCESSIVE_RESOURCE_USAGE"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "DEPENDENCY_DIED"
        ApplicationExitInfo.REASON_OTHER -> "OTHER"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "INITIALIZATION_FAILURE"
        else -> "UNKNOWN"
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
                DownloadsFileLog.write(this, "crash.txt", text)
            } catch (_: Throwable) {
                // Best-effort only; never let logging itself block the real crash handling.
            }
            previousHandler?.uncaughtException(thread, throwable)
        }
    }
}
