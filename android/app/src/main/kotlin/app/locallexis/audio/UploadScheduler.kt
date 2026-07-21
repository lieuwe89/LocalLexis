package app.locallexis.audio

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import java.io.File
import java.util.concurrent.TimeUnit

/** Enqueues a durable, network-constrained upload job for a finished recording. */
object UploadScheduler {
    fun enqueue(context: Context, file: File) {
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setInputData(workDataOf(UploadWorker.KEY_PATH to file.absolutePath))
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "upload-${file.name}",
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    /**
     * Re-enqueue any recording still sitting in local storage. Recordings
     * are deleted only after a successful upload ([UploadWorker]), so anything
     * left here never made it to the hub — e.g. captured while unpaired, or
     * whose upload work was lost. [ExistingWorkPolicy.KEEP] makes this a no-op
     * for uploads already pending, so it's safe to call on every app start.
     */
    fun sweepPending(context: Context) {
        val dir = File(context.filesDir, "recordings")
        for (file in pendingRecordings(dir)) enqueue(context, file)
    }
}

/** Non-empty `.m4a` recordings in [dir]; empty list if the dir is absent. */
fun pendingRecordings(dir: File): List<File> =
    dir.listFiles { f -> f.isFile && f.extension == "m4a" && f.length() > 0L }
        ?.sorted()
        ?: emptyList()
