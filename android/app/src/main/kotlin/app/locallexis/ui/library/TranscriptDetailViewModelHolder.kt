package app.locallexis.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.locallexis.AppGraph

/** Lifecycle wrapper that builds [TranscriptDetailViewModel] for one id. */
class TranscriptDetailViewModelHolder(
    graph: AppGraph,
    transcriptId: String,
) : ViewModel() {
    val vm: TranscriptDetailViewModel = TranscriptDetailViewModel(
        db = graph.db,
        transcriptId = transcriptId,
        scope = viewModelScope,
    )

    companion object {
        fun factory(graph: AppGraph, transcriptId: String): ViewModelProvider.Factory =
            viewModelFactory {
                initializer { TranscriptDetailViewModelHolder(graph, transcriptId) }
            }
    }
}
