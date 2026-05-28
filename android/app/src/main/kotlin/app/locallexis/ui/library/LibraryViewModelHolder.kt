package app.locallexis.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.locallexis.AppGraph

/** Lifecycle wrapper that builds [LibraryViewModel] with viewModelScope. */
class LibraryViewModelHolder(graph: AppGraph) : ViewModel() {
    val vm: LibraryViewModel = LibraryViewModel(
        transcriptDao = graph.db.transcriptDao(),
        sync = graph.librarySync(),
        workspaceId = graph.workspaceId(),
        scope = viewModelScope,
    )

    companion object {
        fun factory(graph: AppGraph): ViewModelProvider.Factory = viewModelFactory {
            initializer { LibraryViewModelHolder(graph) }
        }
    }
}
