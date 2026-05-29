package app.locallexis.audio

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Process-global recording state bridge between [RecordingService] (writer)
 * and the recording screen (reader). A singleton StateFlow avoids the
 * bound-service plumbing for what is a single, app-wide recording session.
 */
object RecordingController {

    enum class Status { Idle, Recording, Paused, Saved, Error }

    data class UiState(
        val status: Status = Status.Idle,
        val elapsedMs: Long = 0L,
        val amplitude: Int = 0,
        val message: String? = null,
    )

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    internal fun recording() {
        _state.value = UiState(Status.Recording)
    }

    internal fun paused() {
        _state.value = _state.value.copy(status = Status.Paused)
    }

    internal fun resumed() {
        _state.value = _state.value.copy(status = Status.Recording)
    }

    internal fun tick(elapsedMs: Long, amplitude: Int) {
        val current = _state.value
        if (current.status == Status.Recording || current.status == Status.Paused) {
            _state.value = current.copy(elapsedMs = elapsedMs, amplitude = amplitude)
        }
    }

    internal fun saved() {
        _state.value = UiState(Status.Saved, message = "Saved. Uploading when connected.")
    }

    internal fun error(message: String?) {
        _state.value = UiState(Status.Error, message = message ?: "Recording failed")
    }

    /** Clear a terminal Saved/Error back to Idle once the user has seen it. */
    fun acknowledge() {
        if (_state.value.status == Status.Saved || _state.value.status == Status.Error) {
            _state.value = UiState()
        }
    }
}
