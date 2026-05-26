package app.locallexis.design

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Parchment = Color(0xFFF2EBDC)
private val Ink = Color(0xFF1A1815)
private val Accent = Color(0xFF7A5C2E)

private val LightColors = lightColorScheme(
    primary = Accent,
    onPrimary = Parchment,
    background = Parchment,
    onBackground = Ink,
    surface = Parchment,
    onSurface = Ink,
)

private val DarkColors = darkColorScheme(
    primary = Accent,
    onPrimary = Ink,
    background = Ink,
    onBackground = Parchment,
    surface = Ink,
    onSurface = Parchment,
)

@Composable
fun LocalLexisTheme(content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) DarkColors else LightColors
    MaterialTheme(colorScheme = colors, content = content)
}
