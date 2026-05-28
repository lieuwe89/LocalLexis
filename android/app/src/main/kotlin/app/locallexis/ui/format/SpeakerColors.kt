package app.locallexis.ui.format

import androidx.compose.ui.graphics.Color

/** Parchment-compatible tints; all keep enough contrast for ink (#1A1815) text. */
internal val SPEAKER_PALETTE: List<Color> = listOf(
    Color(0xFFEADFC6), // warm sand
    Color(0xFFDCE3DA), // sage
    Color(0xFFE6DAE0), // rose-grey
    Color(0xFFD9E0E6), // slate
    Color(0xFFEDE2CA), // gold
    Color(0xFFE0DDD2), // stone
)

/** Deterministic palette index for a speaker name. Stable across runs. */
fun speakerColorIndex(name: String): Int =
    if (SPEAKER_PALETTE.isEmpty()) 0 else Math.floorMod(name.hashCode(), SPEAKER_PALETTE.size)

/** Background tint for a speaker's bubble. */
fun speakerHue(name: String): Color = SPEAKER_PALETTE[speakerColorIndex(name)]
