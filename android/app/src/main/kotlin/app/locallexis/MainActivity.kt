package app.locallexis

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.MainScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            LocalLexisTheme {
                MainScreen()
            }
        }
    }
}
