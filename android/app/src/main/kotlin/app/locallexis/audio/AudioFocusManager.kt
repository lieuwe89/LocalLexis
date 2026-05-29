package app.locallexis.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager

/**
 * Requests audio focus for the recording session and maps focus loss/gain to
 * pause/resume callbacks (e.g. a phone call or Assistant transiently grabs the
 * mic). minSdk 26 guarantees the [AudioFocusRequest] API.
 */
class AudioFocusManager(
    context: Context,
    private val onPause: () -> Unit,
    private val onResume: () -> Unit,
) {
    private val audioManager =
        context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var request: AudioFocusRequest? = null

    private val listener = AudioManager.OnAudioFocusChangeListener { change ->
        when (change) {
            AudioManager.AUDIOFOCUS_LOSS,
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT,
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> onPause()
            AudioManager.AUDIOFOCUS_GAIN -> onResume()
        }
    }

    fun request() {
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setOnAudioFocusChangeListener(listener)
            .build()
        request = req
        audioManager.requestAudioFocus(req)
    }

    fun abandon() {
        request?.let { audioManager.abandonAudioFocusRequest(it) }
        request = null
    }
}
