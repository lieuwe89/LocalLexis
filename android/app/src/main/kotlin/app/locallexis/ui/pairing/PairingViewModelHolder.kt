package app.locallexis.ui.pairing

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.locallexis.AppGraph

/** Lifecycle wrapper that builds [PairingViewModel] with the production exchange. */
class PairingViewModelHolder(graph: AppGraph) : ViewModel() {
    val vm: PairingViewModel = PairingViewModel(
        exchange = graph.pair,
        scope = viewModelScope,
    )

    companion object {
        fun factory(graph: AppGraph): ViewModelProvider.Factory = viewModelFactory {
            initializer { PairingViewModelHolder(graph) }
        }
    }
}
