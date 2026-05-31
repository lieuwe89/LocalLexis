package app.locallexis.ui.pairing

import app.locallexis.data.pairing.PairingFailedException
import app.locallexis.data.pairing.PairingPayloadV1
import app.locallexis.data.pairing.PairingResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface PairingUiState {
    data object Idle : PairingUiState
    data class Exchanging(val payload: PairingPayloadV1, val deviceName: String) : PairingUiState
    data class Paired(val deviceId: String, val workspaceId: String, val lamportObserved: Long) : PairingUiState
    data class Error(val httpStatus: Int, val message: String) : PairingUiState
}

/**
 * Drives the pairing screen state machine. Constructor takes a suspend
 * function for the exchange step so production wiring can pass
 * `pairingClient::exchange` and tests can stub it.
 */
class PairingViewModel(
    private val exchange: suspend (PairingPayloadV1, String) -> PairingResult,
    private val scope: CoroutineScope,
) {

    private val _uiState = MutableStateFlow<PairingUiState>(PairingUiState.Idle)
    val uiState: StateFlow<PairingUiState> = _uiState.asStateFlow()

    // The pairing token from the QR is single-use server-side. If submit
    // fires twice for a single scan (camera analyzer racing recomposition,
    // or any other UI path that hits us before the first exchange returns),
    // the second POST burns the spent token and surfaces a spurious 401
    // even though the first POST already paired the device. Guard with the
    // in-flight Job so subsequent submits are dropped until the current
    // exchange terminates.
    private var inFlight: Job? = null

    fun submit(payload: PairingPayloadV1, deviceName: String) {
        if (inFlight?.isActive == true) return
        _uiState.value = PairingUiState.Exchanging(payload, deviceName)
        inFlight = scope.launch {
            try {
                val result = exchange(payload, deviceName)
                _uiState.value = PairingUiState.Paired(
                    deviceId = result.deviceId,
                    workspaceId = result.workspaceId,
                    lamportObserved = result.lamportObserved,
                )
            } catch (e: PairingFailedException) {
                _uiState.value = PairingUiState.Error(e.httpStatus, e.message ?: "pairing failed")
            } catch (e: Throwable) {
                _uiState.value = PairingUiState.Error(0, e.message ?: e::class.simpleName.orEmpty())
            }
        }
    }

    fun reset() {
        _uiState.value = PairingUiState.Idle
    }
}
