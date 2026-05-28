package app.locallexis.ui.library

import app.locallexis.data.db.LocalLexisDatabase
import app.locallexis.data.db.SegmentEntity
import app.locallexis.data.db.TranscriptEntity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

sealed interface TranscriptDetailUiState {
    data object Loading : TranscriptDetailUiState
    data object NotFound : TranscriptDetailUiState
    data class Ready(
        val transcript: TranscriptEntity,
        val segments: List<SegmentRow>,
    ) : TranscriptDetailUiState
    data class Error(val message: String) : TranscriptDetailUiState
}

data class SegmentRow(
    val index: Int,
    val startSec: Double,
    val endSec: Double,
    val text: String,
    val speakerName: String,
) {
    companion object {
        fun from(segment: SegmentEntity, speakers: Map<String, String>): SegmentRow {
            val speakerId = segment.speakerId
            val name = if (speakerId == null) "" else speakers[speakerId] ?: speakerId
            return SegmentRow(
                index = segment.segmentIndex,
                startSec = segment.startSec,
                endSec = segment.endSec,
                text = segment.text,
                speakerName = name,
            )
        }
    }
}

/**
 * Single-transcript detail VM. Snapshots the row + segments + speakers
 * once when constructed; the read-only block 8 flow does not need
 * Flow-based reactivity yet (CRDT-driven updates land in block 10).
 */
class TranscriptDetailViewModel(
    private val db: LocalLexisDatabase,
    private val transcriptId: String,
    private val scope: CoroutineScope,
) {

    private val _uiState = MutableStateFlow<TranscriptDetailUiState>(TranscriptDetailUiState.Loading)
    val uiState: StateFlow<TranscriptDetailUiState> = _uiState.asStateFlow()

    init {
        scope.launch { load() }
    }

    private suspend fun load() {
        try {
            val transcript = db.transcriptDao().getById(transcriptId)
            if (transcript == null) {
                _uiState.value = TranscriptDetailUiState.NotFound
                return
            }
            val segments = db.segmentDao().forTranscript(transcriptId)
            val speakers = db.speakerDao().forTranscript(transcriptId).first()
                .associate { it.speakerId to it.name }
            _uiState.value = TranscriptDetailUiState.Ready(
                transcript = transcript,
                segments = segments.map { SegmentRow.from(it, speakers) },
            )
        } catch (e: Throwable) {
            _uiState.value = TranscriptDetailUiState.Error(e.message ?: "load failed")
        }
    }
}
