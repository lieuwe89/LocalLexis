package app.locallexis.ui.pairing

import app.locallexis.data.pairing.PairingFailedException
import app.locallexis.data.pairing.PairingPayloadV1
import app.locallexis.data.pairing.PairingResult
import kotlinx.coroutines.CoroutineScope
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

    fun submit(payload: PairingPayloadV1, deviceName: String) {
        _uiState.value = PairingUiState.Exchanging(payload, deviceName)
        scope.launch {
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
