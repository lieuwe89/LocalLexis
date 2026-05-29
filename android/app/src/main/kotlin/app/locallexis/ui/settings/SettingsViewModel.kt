package app.locallexis.ui.settings

import app.locallexis.data.config.HubConfigStore
import app.locallexis.data.pairing.DeviceIdentityStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface SyncStatus {
    data object Idle : SyncStatus
    data object Running : SyncStatus
    data object Success : SyncStatus
    data class Failed(val message: String) : SyncStatus
}

data class SettingsUiState(
    val paired: Boolean,
    val hubUrl: String?,
    val workspaceId: String?,
    val tlsPinned: Boolean,
    val deviceId: String?,
    val sync: SyncStatus,
)

/**
 * Settings state: a snapshot of the current pairing plus a manual-sync action
 * and an unpair action. Snapshot is re-read after unpair and whenever
 * [refresh] is called (the screen calls it on entry, since pairing may have
 * changed on another tab). [clearIdentity] and [runSync] are injected so the
 * VM is testable without Android stores or a real hub.
 */
class SettingsViewModel(
    private val hubConfig: HubConfigStore,
    private val deviceIdentityStore: DeviceIdentityStore,
    private val clearIdentity: () -> Unit,
    private val runSync: suspend () -> Unit,
    private val scope: CoroutineScope,
) {
    private val _state = MutableStateFlow(snapshot(SyncStatus.Idle))
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    private fun snapshot(sync: SyncStatus) = SettingsUiState(
        paired = hubConfig.isPaired(),
        hubUrl = hubConfig.getHubUrl(),
        workspaceId = hubConfig.getWorkspaceId(),
        tlsPinned = hubConfig.getTlsSpkiB64() != null,
        deviceId = deviceIdentityStore.getDeviceId(),
        sync = sync,
    )

    fun refresh() {
        _state.value = snapshot(_state.value.sync)
    }

    fun syncNow() {
        if (!hubConfig.isPaired()) return
        _state.value = snapshot(SyncStatus.Running)
        scope.launch {
            _state.value = try {
                runSync()
                snapshot(SyncStatus.Success)
            } catch (e: Throwable) {
                snapshot(SyncStatus.Failed(e.message ?: "sync failed"))
            }
        }
    }

    fun unpair() {
        clearIdentity()
        _state.value = snapshot(SyncStatus.Idle)
    }
}
