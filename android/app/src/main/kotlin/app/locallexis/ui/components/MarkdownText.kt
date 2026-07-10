package app.locallexis.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import app.locallexis.ui.format.MdBlock
import app.locallexis.ui.format.MdSpan
import app.locallexis.ui.format.parseMarkdown

/** Renders the markdown subset produced by [parseMarkdown]. */
@Composable
fun MarkdownText(markdown: String, modifier: Modifier = Modifier) {
    val blocks = remember(markdown) { parseMarkdown(markdown) }
    Column(modifier) {
        blocks.forEach { block ->
            when (block) {
                is MdBlock.Heading -> Text(
                    text = annotate(block.spans),
                    style = when (block.level) {
                        1 -> MaterialTheme.typography.titleMedium
                        2 -> MaterialTheme.typography.titleSmall
                        else -> MaterialTheme.typography.labelLarge
                    },
                    modifier = Modifier.padding(top = 8.dp, bottom = 2.dp),
                )
                is MdBlock.ListItem -> Row(Modifier.padding(vertical = 1.dp)) {
                    Text(
                        text = block.marker,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(end = 6.dp),
                    )
                    Text(annotate(block.spans), style = MaterialTheme.typography.bodyMedium)
                }
                is MdBlock.Paragraph -> Text(
                    text = annotate(block.spans),
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(vertical = 2.dp),
                )
            }
        }
    }
}

private fun annotate(spans: List<MdSpan>): AnnotatedString = buildAnnotatedString {
    spans.forEach { s ->
        withStyle(
            SpanStyle(
                fontWeight = if (s.bold) FontWeight.Bold else null,
                fontStyle = if (s.italic) FontStyle.Italic else null,
            )
        ) { append(s.text) }
    }
}
