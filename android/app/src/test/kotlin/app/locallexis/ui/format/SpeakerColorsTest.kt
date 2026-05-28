package app.locallexis.ui.format

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeakerColorsTest {
    @Test fun index_is_deterministic() =
        assertEquals(speakerColorIndex("Alvarez"), speakerColorIndex("Alvarez"))

    @Test fun index_in_palette_range() {
        listOf("Chair", "Alvarez", "Ruiz", "SPEAKER_00", "", "x").forEach { name ->
            val i = speakerColorIndex(name)
            assertTrue("index $i out of range for '$name'", i in SPEAKER_PALETTE.indices)
        }
    }
}
