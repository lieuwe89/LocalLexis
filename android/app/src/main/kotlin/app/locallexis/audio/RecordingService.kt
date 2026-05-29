package app.locallexis.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import app.locallexis.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.Locale

/**
 * Foreground service (type microphone) that owns the recording session: starts
 * MediaRecorder, holds audio focus, ticks elapsed time + amplitude into
 * [RecordingController], and on stop hands the finished file to
 * [UploadScheduler]. Background recording on Android requires a foreground
 * service with a persistent notification (mandatory since API 28; typed since
 * API 29/34).
 */
class RecordingService : Service() {

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private lateinit var engine: RecordingEngine
    private lateinit var focus: AudioFocusManager
    private var ticker: Job? = null
    private var startedAt = 0L
    private var pausedAccumMs = 0L
    private var pausedAt = 0L

    override fun onCreate() {
        super.onCreate()
        engine = RecordingEngine(this)
        focus = AudioFocusManager(this, onPause = ::pauseFromFocus, onResume = ::resumeFromFocus)
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startRecording()
            ACTION_STOP -> stopRecording()
        }
        return START_STICKY
    }

    private fun startRecording() {
        if (RecordingController.state.value.status == RecordingController.Status.Recording) return
        startInForeground(0L)
        try {
            engine.start()
            focus.request()
            startedAt = SystemClock.elapsedRealtime()
            pausedAccumMs = 0L
            RecordingController.recording()
            startTicker()
        } catch (e: Exception) {
            engine.cancel()
            focus.abandon()
            RecordingController.error(e.message)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun startTicker() {
        ticker?.cancel()
        ticker = scope.launch {
            while (isActive) {
                if (RecordingController.state.value.status == RecordingController.Status.Recording) {
                    val elapsed = SystemClock.elapsedRealtime() - startedAt - pausedAccumMs
                    RecordingController.tick(elapsed, engine.maxAmplitude())
                    updateNotification(elapsed)
                }
                delay(TICK_MS)
            }
        }
    }

    private fun pauseFromFocus() {
        if (RecordingController.state.value.status != RecordingController.Status.Recording) return
        engine.pause()
        pausedAt = SystemClock.elapsedRealtime()
        RecordingController.paused()
    }

    private fun resumeFromFocus() {
        if (RecordingController.state.value.status != RecordingController.Status.Paused) return
        engine.resume()
        pausedAccumMs += SystemClock.elapsedRealtime() - pausedAt
        RecordingController.resumed()
    }

    private fun stopRecording() {
        ticker?.cancel()
        focus.abandon()
        val file = engine.stop()
        if (file != null && file.length() > 0L) {
            UploadScheduler.enqueue(applicationContext, file)
            RecordingController.saved()
        } else {
            RecordingController.error("Recording was too short to save")
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        ticker?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startInForeground(elapsedMs: Long) {
        val notification = buildNotification(elapsedMs)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Recording",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { setShowBadge(false) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(elapsedMs: Long): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            Intent(this, RecordingService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("LocalLexis is recording")
            .setContentText(formatElapsed(elapsedMs))
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stop)
            .build()
    }

    private fun updateNotification(elapsedMs: Long) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIF_ID, buildNotification(elapsedMs))
    }

    companion object {
        const val ACTION_START = "app.locallexis.action.START_RECORDING"
        const val ACTION_STOP = "app.locallexis.action.STOP_RECORDING"
        private const val CHANNEL_ID = "recording"
        private const val NOTIF_ID = 1001
        private const val TICK_MS = 500L

        fun start(context: Context) {
            ContextCompat.startForegroundService(
                context,
                Intent(context, RecordingService::class.java).setAction(ACTION_START),
            )
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, RecordingService::class.java).setAction(ACTION_STOP),
            )
        }
    }
}

internal fun formatElapsed(ms: Long): String {
    val totalSeconds = ms / 1000
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return String.format(Locale.US, "%02d:%02d", minutes, seconds)
}
