package app.locallexis

import android.app.Application
import app.locallexis.audio.UploadScheduler

class App : Application() {
    val graph: AppGraph by lazy { AppGraph(this) }

    override fun onCreate() {
        super.onCreate()
        // Recordings captured while unpaired (or whose upload work was lost)
        // stay on disk until uploaded; re-enqueue them so they don't wait on
        // WorkManager's backoff. KEEP makes this a no-op for pending uploads.
        UploadScheduler.sweepPending(this)
    }
}
