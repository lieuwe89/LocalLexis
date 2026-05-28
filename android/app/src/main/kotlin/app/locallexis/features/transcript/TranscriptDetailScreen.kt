package app.locallexis.features.transcript

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.locallexis.appGraph
import app.locallexis.data.db.TranscriptEntity
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.components.CenteredProgress
import app.locallexis.ui.components.CenteredText
import app.locallexis.ui.format.formatDate
import app.locallexis.ui.format.formatDuration
import app.locallexis.ui.format.speakerHue
import app.locallexis.ui.library.SegmentRow
import app.locallexis.ui.library.TranscriptDetailUiState
import app.locallexis.ui.library.TranscriptDetailViewModelHolder

@Composable
fun TranscriptDetailScreen(transcriptId: String) {
    val context = LocalContext.current
    val graph = remember(context) { context.appGraph }
    val holder: TranscriptDetailViewModelHolder =
        viewModel(factory = TranscriptDetailViewModelHolder.factory(graph, transcriptId))
    val state by holder.vm.uiState.collectAsState()
    TranscriptDetailContent(state)
}

@Composable
fun TranscriptDetailContent(state: TranscriptDetailUiState) {
    when (state) {
        is TranscriptDetailUiState.Loading -> CenteredProgress()
        is TranscriptDetailUiState.NotFound -> CenteredText("Transcript not found.")
        is TranscriptDetailUiState.Error -> CenteredText(state.message)
        is TranscriptDetailUiState.Ready -> ReadyDetail(state.transcript, state.segments)
    }
}

@Composable
private fun ReadyDetail(transcript: TranscriptEntity, segments: List<SegmentRow>) {
    val speakerCount = segments.map { it.speakerName }.filter { it.isNotBlank() }.distinct().size
    Column(Modifier.fillMaxSize()) {
        DetailHeader(transcript, speakerCount)
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        ) {
            items(segments, key = { it.index }) { seg ->
                SegmentBubble(seg)
            }
        }
    }
}

@Composable
private fun DetailHeader(transcript: TranscriptEntity, speakerCount: Int) {
    Column(Modifier.fillMaxWidth().padding(16.dp)) {
        Text(
            text = transcript.audioBasename ?: transcript.id,
            style = MaterialTheme.typography.headlineSmall,
        )
        val meta = listOfNotNull(
            formatDate(transcript.createdAt).ifBlank { null },
            formatDuration(transcript.durationSeconds).ifBlank { null },
            transcript.language,
            if (speakerCount > 0) "$speakerCount speakers" else null,
        ).joinToString(" · ")
        Text(
            text = meta,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

@Composable
private fun SegmentBubble(seg: SegmentRow) {
    Surface(
        color = speakerHue(seg.speakerName),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    ) {
        Column(Modifier.padding(10.dp)) {
            val label = listOfNotNull(
                seg.speakerName.ifBlank { null },
                formatDuration(seg.startSec).ifBlank { null },
            ).joinToString(" · ")
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                text = seg.text,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

private val previewTranscript = TranscriptEntity(
    id = "1",
    workspaceId = "ws",
    audioPath = "/x/council-2026-05-12.wav",
    audioBasename = "council-2026-05-12",
    durationSeconds = 872.0,
    language = "en",
    createdAt = "2026-05-12T14:32:00Z",
    jsonMtime = 0.0,
    modelsAsr = null,
    modelsDiarizer = null,
    rawJson = "{}",
)

private val previewSegments = listOf(
    SegmentRow(0, 0.0, 6.0, "Let's call the meeting to order.", "Chair"),
    SegmentRow(1, 6.0, 14.0, "Thank you. First item is the parks budget.", "Alvarez"),
    SegmentRow(2, 14.0, 20.0, "I move we table it until the survey lands.", "Ruiz"),
    SegmentRow(3, 20.0, 27.0, "Noted for the record.", ""),
)

@Preview(showBackground = true)
@Composable
private fun DetailReadyPreview() {
    LocalLexisTheme {
        TranscriptDetailContent(
            TranscriptDetailUiState.Ready(previewTranscript, previewSegments),
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun DetailNotFoundPreview() {
    LocalLexisTheme { TranscriptDetailContent(TranscriptDetailUiState.NotFound) }
}
