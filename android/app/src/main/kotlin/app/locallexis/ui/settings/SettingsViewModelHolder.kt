package app.locallexis.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.locallexis.AppGraph

/** Lifecycle wrapper that builds [SettingsViewModel] with viewModelScope. */
class SettingsViewModelHolder(graph: AppGraph) : ViewModel() {
    val vm: SettingsViewModel = SettingsViewModel(
        hubConfig = graph.hubConfig,
        deviceIdentityStore = graph.deviceIdentityStore,
        clearIdentity = graph::unpair,
        runSync = { graph.librarySync().incremental(graph.workspaceId()) },
        scope = viewModelScope,
    )

    companion object {
        fun factory(graph: AppGraph): ViewModelProvider.Factory = viewModelFactory {
            initializer { SettingsViewModelHolder(graph) }
        }
    }
}
