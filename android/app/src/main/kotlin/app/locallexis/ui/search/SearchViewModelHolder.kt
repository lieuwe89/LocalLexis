package app.locallexis.ui.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.locallexis.AppGraph

/** Lifecycle wrapper that builds [SearchViewModel] with viewModelScope. */
class SearchViewModelHolder(graph: AppGraph) : ViewModel() {
    val vm: SearchViewModel = SearchViewModel(
        searchDao = graph.db.searchDao(),
        scope = viewModelScope,
    )

    companion object {
        fun factory(graph: AppGraph): ViewModelProvider.Factory = viewModelFactory {
            initializer { SearchViewModelHolder(graph) }
        }
    }
}
