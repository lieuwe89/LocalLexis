package app.locallexis.features.transcript

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.components.MarkdownText
import app.locallexis.ui.format.formatDateTime

/** Collapsible card showing the hub-generated LLM summary. */
@Composable
fun SummaryCard(
    summary: String,
    model: String?,
    createdAt: String?,
    modifier: Modifier = Modifier,
) {
    var expanded by rememberSaveable { mutableStateOf(true) }
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Summary", style = MaterialTheme.typography.titleSmall)
                    val caption = listOfNotNull(
                        model,
                        formatDateTime(createdAt).ifBlank { null },
                    ).joinToString(" · ")
                    if (caption.isNotBlank()) {
                        Text(
                            text = caption,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Icon(
                    imageVector = if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = if (expanded) "Collapse summary" else "Expand summary",
                )
            }
            if (expanded) {
                MarkdownText(summary, Modifier.padding(top = 6.dp))
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun SummaryCardPreview() {
    LocalLexisTheme {
        SummaryCard(
            summary = "# Recap\nThe council **approved** the parks budget.\n" +
                "- Survey lands *next week*\n- 1. follow-up scheduled",
            model = "Qwen3-30B-A3B-Instruct-2507-GGUF",
            createdAt = "2026-07-09T12:00:00Z",
        )
    }
}
