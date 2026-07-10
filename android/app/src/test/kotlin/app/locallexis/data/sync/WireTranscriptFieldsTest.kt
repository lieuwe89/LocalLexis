package app.locallexis.data.sync

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WireTranscriptFieldsTest {

    // Same settings as SyncClient's Json instance.
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Test
    fun parsesTitleSummaryAndMeta() {
        val doc = """
            {"id":"t1","title":"Council meeting","summary":"# Recap\n- first item",
             "summary_meta":{"model":"Qwen3-30B-A3B-Instruct-2507-GGUF","provider":"lemonade",
             "created_at":"2026-07-09T12:00:00Z"}}
        """.trimIndent()

        val parsed = json.decodeFromString(WireTranscript.serializer(), doc)

        assertEquals("Council meeting", parsed.title)
        assertEquals("# Recap\n- first item", parsed.summary)
        assertEquals("Qwen3-30B-A3B-Instruct-2507-GGUF", parsed.summaryMeta?.model)
        assertEquals("2026-07-09T12:00:00Z", parsed.summaryMeta?.createdAt)
    }

    @Test
    fun absentFieldsAreNull() {
        val parsed = json.decodeFromString(WireTranscript.serializer(), """{"id":"t1"}""")
        assertNull(parsed.title)
        assertNull(parsed.summary)
        assertNull(parsed.summaryMeta)
    }

    @Test
    fun metaWithMissingKeysYieldsNullMembers() {
        val parsed = json.decodeFromString(
            WireTranscript.serializer(),
            """{"id":"t1","summary":"text","summary_meta":{}}""",
        )
        assertEquals("text", parsed.summary)
        assertNull(parsed.summaryMeta?.model)
        assertNull(parsed.summaryMeta?.createdAt)
    }
}
