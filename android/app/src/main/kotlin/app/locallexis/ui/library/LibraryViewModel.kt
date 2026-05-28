package app.locallexis.ui.library

import app.locallexis.data.db.TranscriptDao
import app.locallexis.data.db.TranscriptEntity
import app.locallexis.data.sync.LibrarySync
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface LibraryUiState {
    data object Loading : LibraryUiState
    data class Ready(val transcripts: List<TranscriptSummary>) : LibraryUiState
    data class Error(val message: String) : LibraryUiState
}

data class TranscriptSummary(
    val id: String,
    val audioBasename: String?,
    val language: String?,
    val createdAt: String?,
    val durationSeconds: Double?,
) {
    companion object {
        fun fromEntity(e: TranscriptEntity) = TranscriptSummary(
            id = e.id,
            audioBasename = e.audioBasename,
            language = e.language,
            createdAt = e.createdAt,
            durationSeconds = e.durationSeconds,
        )
    }
}

/**
 * Library screen state. Reads transcript rows from Room via a Flow,
 * drives [LibrarySync.incremental] on [refresh]. Sync failures surface
 * via [lastError] without clearing the visible row list, so the user
 * keeps seeing their local library even when the hub is unreachable.
 *
 * [scope] is configurable to make tests deterministic; production
 * Android usage wires this to the platform `viewModelScope` via a
 * factory.
 */
class LibraryViewModel(
    private val transcriptDao: TranscriptDao,
    private val sync: LibrarySync,
    private val workspaceId: String,
    private val scope: CoroutineScope,
) {

    val uiState: StateFlow<LibraryUiState> = transcriptDao.listAll()
        .map<List<TranscriptEntity>, LibraryUiState> { rows ->
            LibraryUiState.Ready(rows.map(TranscriptSummary::fromEntity))
        }
        .catch { emit(LibraryUiState.Error(it.message ?: "unknown error")) }
        .stateIn(scope, SharingStarted.WhileSubscribed(5_000), LibraryUiState.Loading)

    private val _lastError = MutableStateFlow<String?>(null)
    val lastError: StateFlow<String?> = _lastError.asStateFlow()

    fun refresh() {
        scope.launch {
            try {
                sync.incremental(workspaceId)
                _lastError.value = null
            } catch (e: Throwable) {
                _lastError.value = e.message ?: e::class.simpleName ?: "sync failed"
            }
        }
    }
}
