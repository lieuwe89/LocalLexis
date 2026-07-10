package app.locallexis.ui.format

/**
 * Minimal line-oriented markdown model for LLM summaries. Covers the
 * subset the summarizer actually emits — #/##/### headings, bullet and
 * numbered list items, **bold**, *italic*. Anything else passes through
 * as plain paragraph text. Deliberately not a spec-compliant parser;
 * see the design doc (2026-07-10-android-parity-design.md).
 *
 * Known tradeoffs: triple-asterisk emphasis (***text***) renders with
 * stray literal asterisks (nested emphasis is unsupported), and leading
 * indentation is trimmed so nested/indented list items flatten to top level.
 */
sealed interface MdBlock {
    data class Heading(val level: Int, val spans: List<MdSpan>) : MdBlock
    data class Paragraph(val spans: List<MdSpan>) : MdBlock
    data class ListItem(val ordered: Boolean, val marker: String, val spans: List<MdSpan>) : MdBlock
}

data class MdSpan(val text: String, val bold: Boolean = false, val italic: Boolean = false)

private val HEADING = Regex("""^(#{1,3})\s+(.*)$""")
private val BULLET = Regex("""^[-*]\s+(.*)$""")
private val ORDERED = Regex("""^(\d+)\.\s+(.*)$""")

fun parseMarkdown(text: String): List<MdBlock> =
    text.lines().mapNotNull { raw ->
        val line = raw.trim()
        if (line.isEmpty()) return@mapNotNull null
        HEADING.matchEntire(line)?.let {
            return@mapNotNull MdBlock.Heading(it.groupValues[1].length, parseSpans(it.groupValues[2]))
        }
        BULLET.matchEntire(line)?.let {
            return@mapNotNull MdBlock.ListItem(false, "•", parseSpans(it.groupValues[1]))
        }
        ORDERED.matchEntire(line)?.let {
            return@mapNotNull MdBlock.ListItem(true, "${it.groupValues[1]}.", parseSpans(it.groupValues[2]))
        }
        MdBlock.Paragraph(parseSpans(line))
    }

fun parseSpans(line: String): List<MdSpan> {
    val spans = mutableListOf<MdSpan>()
    val sb = StringBuilder()
    fun flush() {
        if (sb.isNotEmpty()) {
            spans.add(MdSpan(sb.toString()))
            sb.clear()
        }
    }
    var i = 0
    while (i < line.length) {
        when {
            line.startsWith("**", i) -> {
                val end = line.indexOf("**", i + 2)
                if (end == -1) { sb.append(line[i]); i++ } else {
                    flush()
                    spans.add(MdSpan(line.substring(i + 2, end), bold = true))
                    i = end + 2
                }
            }
            line[i] == '*' -> {
                val end = line.indexOf('*', i + 1)
                if (end == -1) { sb.append(line[i]); i++ } else {
                    flush()
                    spans.add(MdSpan(line.substring(i + 1, end), italic = true))
                    i = end + 1
                }
            }
            else -> { sb.append(line[i]); i++ }
        }
    }
    flush()
    return spans
}
