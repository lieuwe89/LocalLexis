package app.locallexis.ui

import app.locallexis.data.pairing.PairingClient
import app.locallexis.data.pairing.PairingFailedException
import app.locallexis.data.pairing.PairingPayloadV1
import app.locallexis.data.pairing.PairingResult
import app.locallexis.ui.pairing.PairingUiState
import app.locallexis.ui.pairing.PairingViewModel
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PairingViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private val samplePayload = PairingPayloadV1(
        hubUrl = "https://h",
        workspaceId = "ws_a",
        token = "tok",
        tlsSpkiB64 = null,
    )

    @Test
    fun idleByDefault() = runTest(testDispatcher) {
        val vm = PairingViewModel(
            exchange = { _, _ -> error("not called") },
            scope = TestScope(testDispatcher),
        )
        assertEquals(PairingUiState.Idle, vm.uiState.value)
    }

    @Test
    fun submitTransitionsThroughExchangingToPaired() = runTest(testDispatcher) {
        val gate = CompletableDeferred<PairingResult>()
        val vm = PairingViewModel(
            exchange = { _, _ -> gate.await() },
            scope = TestScope(testDispatcher),
        )

        vm.submit(samplePayload, "Pixel 8")
        advanceUntilIdle()
        assertTrue(vm.uiState.value is PairingUiState.Exchanging)

        gate.complete(
            PairingResult(deviceId = "dev_1", workspaceId = "ws_a", lamportObserved = 0)
        )
        advanceUntilIdle()
        val state = vm.uiState.first { it is PairingUiState.Paired }
        val paired = state as PairingUiState.Paired
        assertEquals("dev_1", paired.deviceId)
        assertEquals("ws_a", paired.workspaceId)
    }

    @Test
    fun pairingFailureSurfacesError() = runTest(testDispatcher) {
        val vm = PairingViewModel(
            exchange = { _, _ -> throw PairingFailedException(401, "bad token") },
            scope = TestScope(testDispatcher),
        )

        vm.submit(samplePayload, "Phone")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state is PairingUiState.Error)
        assertEquals(401, (state as PairingUiState.Error).httpStatus)
    }

    @Test
    fun resetReturnsToIdle() = runTest(testDispatcher) {
        val vm = PairingViewModel(
            exchange = { _, _ -> throw PairingFailedException(0, "x") },
            scope = TestScope(testDispatcher),
        )
        vm.submit(samplePayload, "Phone")
        advanceUntilIdle()
        assertTrue(vm.uiState.value is PairingUiState.Error)

        vm.reset()
        assertEquals(PairingUiState.Idle, vm.uiState.value)
    }
}
