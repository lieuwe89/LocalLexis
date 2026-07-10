package app.locallexis.ui.format

import org.junit.Assert.assertEquals
import org.junit.Test

class MarkdownTest {

    @Test
    fun headingLevels() {
        val blocks = parseMarkdown("# One\n## Two\n### Three")
        assertEquals(
            listOf(1, 2, 3),
            blocks.map { (it as MdBlock.Heading).level },
        )
        assertEquals("One", (blocks[0] as MdBlock.Heading).spans.single().text)
    }

    @Test
    fun bulletAndOrderedLists() {
        val blocks = parseMarkdown("- alpha\n* beta\n1. gamma\n12. delta")
        val items = blocks.map { it as MdBlock.ListItem }
        assertEquals(listOf("•", "•", "1.", "12."), items.map { it.marker })
        assertEquals(listOf(false, false, true, true), items.map { it.ordered })
        assertEquals("alpha", items[0].spans.single().text)
    }

    @Test
    fun boldAndItalicSpans() {
        val spans = parseSpans("plain **bold** and *ital* end")
        assertEquals(
            listOf(
                MdSpan("plain "),
                MdSpan("bold", bold = true),
                MdSpan(" and "),
                MdSpan("ital", italic = true),
                MdSpan(" end"),
            ),
            spans,
        )
    }

    @Test
    fun unterminatedMarkersRenderLiterally() {
        assertEquals(listOf(MdSpan("a **b and c")), parseSpans("a **b and c"))
    }

    @Test
    fun boldLineIsNotABullet() {
        val block = parseMarkdown("**Key point** here").single()
        val spans = (block as MdBlock.Paragraph).spans
        assertEquals(MdSpan("Key point", bold = true), spans[0])
        assertEquals(MdSpan(" here"), spans[1])
    }

    @Test
    fun blankLinesDropped_plainLinesAreParagraphs() {
        val blocks = parseMarkdown("first\n\nsecond\n")
        assertEquals(2, blocks.size)
        assertEquals("first", (blocks[0] as MdBlock.Paragraph).spans.single().text)
    }

    @Test
    fun fourHashesIsPlainText() {
        val block = parseMarkdown("#### deep heading").single()
        assertEquals("#### deep heading", (block as MdBlock.Paragraph).spans.single().text)
    }
}
