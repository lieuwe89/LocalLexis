package app.locallexis.audio

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Thin MediaRecorder wrapper producing AAC-LC mono ~32 kbps in an MPEG-4
 * (.m4a) container, written to app-private storage. The filename is kept
 * within the hub's safe-basename rules (letters, digits, dot, dash) so it can
 * be sent verbatim as the upload's `?filename=`.
 */
class RecordingEngine(private val context: Context) {

    private var recorder: MediaRecorder? = null
    private var currentFile: File? = null

    val outputFile: File? get() = currentFile

    fun start(): File {
        val dir = File(context.filesDir, "recordings").apply { mkdirs() }
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        val file = File(dir, "rec-$stamp.m4a")
        val r = newRecorder()
        r.setAudioSource(MediaRecorder.AudioSource.MIC)
        r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        r.setAudioChannels(1)
        r.setAudioSamplingRate(44_100)
        r.setAudioEncodingBitRate(32_000)
        r.setOutputFile(file.absolutePath)
        r.prepare()
        r.start()
        recorder = r
        currentFile = file
        return file
    }

    fun pause() {
        recorder?.pause()
    }

    fun resume() {
        recorder?.resume()
    }

    fun maxAmplitude(): Int = try {
        recorder?.maxAmplitude ?: 0
    } catch (_: Exception) {
        0
    }

    /** Stops + releases; returns the finished file, or null if nothing usable was captured. */
    fun stop(): File? {
        val r = recorder ?: return null
        val file = currentFile
        return try {
            r.stop()
            file
        } catch (_: RuntimeException) {
            // MediaRecorder.stop() throws if stopped before any frames were written.
            file?.delete()
            null
        } finally {
            r.release()
            recorder = null
            currentFile = null
        }
    }

    fun cancel() {
        val r = recorder ?: return
        try {
            r.stop()
        } catch (_: RuntimeException) {
            // ignore: discarding anyway
        }
        r.release()
        currentFile?.delete()
        recorder = null
        currentFile = null
    }

    private fun newRecorder(): MediaRecorder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
}
