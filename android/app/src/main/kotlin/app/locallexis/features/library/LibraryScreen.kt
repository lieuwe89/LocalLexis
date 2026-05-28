package app.locallexis.features.library

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.locallexis.appGraph
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.components.CenteredMessage
import app.locallexis.ui.components.CenteredProgress
import app.locallexis.ui.components.ErrorBanner
import app.locallexis.ui.format.formatDate
import app.locallexis.ui.format.formatDuration
import app.locallexis.ui.library.LibraryUiState
import app.locallexis.ui.library.LibraryViewModelHolder
import app.locallexis.ui.library.TranscriptSummary

@Composable
fun LibraryScreen(onOpen: (String) -> Unit) {
    val context = LocalContext.current
    val graph = remember(context) { context.appGraph }
    val holder: LibraryViewModelHolder = viewModel(factory = LibraryViewModelHolder.factory(graph))
    val state by holder.vm.uiState.collectAsState()
    val lastError by holder.vm.lastError.collectAsState()
    LibraryContent(
        state = state,
        lastError = lastError,
        onOpen = onOpen,
        onRefresh = holder.vm::refresh,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryContent(
    state: LibraryUiState,
    lastError: String?,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Library") },
                actions = {
                    IconButton(onClick = onRefresh) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (lastError != null) ErrorBanner(lastError)
            when (state) {
                is LibraryUiState.Loading -> CenteredProgress()
                is LibraryUiState.Error -> CenteredMessage(state.message, onRetry = onRefresh)
                is LibraryUiState.Ready ->
                    if (state.transcripts.isEmpty()) EmptyLibrary()
                    else TranscriptList(state.transcripts, onOpen)
            }
        }
    }
}

@Composable
private fun TranscriptList(items: List<TranscriptSummary>, onOpen: (String) -> Unit) {
    LazyColumn(Modifier.fillMaxSize()) {
        items(items, key = { it.id }) { item ->
            TranscriptRow(item, onOpen)
            HorizontalDivider()
        }
    }
}

@Composable
private fun TranscriptRow(item: TranscriptSummary, onOpen: (String) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onOpen(item.id) }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text = item.audioBasename ?: item.id,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val meta = listOfNotNull(
                formatDate(item.createdAt).ifBlank { null },
                item.language,
            ).joinToString(" · ")
            if (meta.isNotBlank()) {
                Text(
                    text = meta,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
            }
        }
        val dur = formatDuration(item.durationSeconds)
        if (dur.isNotBlank()) {
            Text(
                text = dur,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun EmptyLibrary() {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("No transcripts yet", style = MaterialTheme.typography.titleMedium)
        Text(
            "Pair a hub to sync your library.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

private val previewItems = listOf(
    TranscriptSummary("1", "council-2026-05-12", "en", "2026-05-12T14:32:00Z", 872.0),
    TranscriptSummary("2", "deposition-ramirez", "es", "2026-05-10T09:00:00Z", 3737.0),
    TranscriptSummary("3", "standup-0508", "en", "2026-05-08T08:45:00Z", 525.0),
)

@Preview(showBackground = true)
@Composable
private fun LibraryReadyPreview() {
    LocalLexisTheme {
        LibraryContent(LibraryUiState.Ready(previewItems), null, {}, {})
    }
}

@Preview(showBackground = true)
@Composable
private fun LibraryEmptyPreview() {
    LocalLexisTheme {
        LibraryContent(LibraryUiState.Ready(emptyList()), null, {}, {})
    }
}

@Preview(showBackground = true)
@Composable
private fun LibraryErrorBannerPreview() {
    LocalLexisTheme {
        LibraryContent(LibraryUiState.Ready(previewItems), "no hub paired — pair a hub to sync", {}, {})
    }
}

@Preview(showBackground = true)
@Composable
private fun LibraryLoadingPreview() {
    LocalLexisTheme { LibraryContent(LibraryUiState.Loading, null, {}, {}) }
}
