package xyz.imlazy.smsingest

import android.app.Application

class SmsIngestApplication : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        // Idempotent (ExistingPeriodicWorkPolicy.KEEP) — safe to call on every start.
        container.syncScheduler.ensurePeriodicSync()
    }
}
