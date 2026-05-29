package app.locallexis.audio

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.locallexis.appGraph
import app.locallexis.data.http.HubTls
import app.locallexis.data.pairing.SignLargeBody
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.IOException

/**
 * Durable background upload of one recording to the hub's signed
 * `POST /jobs/upload`. The request carries the [SignLargeBody] tag so the
 * signing interceptor signs the whole file body (the hub verifies over the raw
 * bytes). Retries on network failure / 5xx; gives up on 4xx (a signature or
 * filename problem won't fix itself by retrying). Not-yet-paired is a retry so
 * a recording captured before pairing still uploads once the hub is set.
 */
class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val path = inputData.getString(KEY_PATH) ?: return Result.failure()
        val file = File(path)
        if (!file.exists() || file.length() == 0L) return Result.failure()

        val graph = applicationContext.appGraph
        val base = graph.hubConfig.getHubUrl() ?: return Result.retry()
        val client = HubTls.pinnedClient(graph.okHttp, base, graph.hubConfig.getTlsSpkiB64())

        val request = Request.Builder()
            .url(uploadUrl(base, file.name))
            .post(file.asRequestBody(AUDIO_MP4))
            .tag(SignLargeBody::class.java, SignLargeBody)
            .build()

        return try {
            client.newCall(request).execute().use { resp ->
                when {
                    resp.isSuccessful -> {
                        file.delete()
                        Result.success()
                    }
                    resp.code in 500..599 -> Result.retry()
                    else -> Result.failure()
                }
            }
        } catch (_: IOException) {
            Result.retry()
        }
    }

    companion object {
        const val KEY_PATH = "file_path"
        private val AUDIO_MP4 = "audio/mp4".toMediaType()
    }
}

/** `<base>/jobs/upload?filename=<name>`, with the filename query properly encoded. */
fun uploadUrl(baseUrl: String, filename: String): String =
    baseUrl.trimEnd('/').toHttpUrl().newBuilder()
        .addPathSegments("jobs/upload")
        .addQueryParameter("filename", filename)
        .build()
        .toString()
