package app.locallexis.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import app.locallexis.features.library.LibraryScreen
import app.locallexis.features.pairing.PairingScreen
import app.locallexis.features.recording.RecordingScreen
import app.locallexis.features.settings.SettingsScreen
import app.locallexis.features.transcript.TranscriptDetailScreen

private data class NavItem(
    val route: String,
    val label: String,
    val icon: ImageVector,
)

private val navItems = listOf(
    NavItem("library", "Library", Icons.Filled.Folder),
    NavItem("recording", "Record", Icons.Filled.Mic),
    NavItem("pairing", "Pair", Icons.Filled.QrCodeScanner),
    NavItem("settings", "Settings", Icons.Filled.Settings),
)

@Composable
fun MainScreen() {
    val nav = rememberNavController()
    val backStackEntry by nav.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route

    Scaffold(
        bottomBar = {
            NavigationBar {
                navItems.forEach { item ->
                    NavigationBarItem(
                        selected = currentRoute == item.route ||
                            backStackEntry?.destination?.hierarchy?.any { it.route == item.route } == true,
                        onClick = {
                            nav.navigate(item.route) {
                                popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(item.icon, contentDescription = item.label) },
                        label = { Text(item.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = nav,
            startDestination = "library",
            modifier = Modifier.padding(padding),
        ) {
            composable("library") { LibraryScreen(onOpen = { id -> nav.navigate("transcript/$id") }) }
            composable("recording") { RecordingScreen() }
            composable("pairing") { PairingScreen() }
            composable("settings") { SettingsScreen() }
            composable("transcript/{transcriptId}") { entry ->
                TranscriptDetailScreen(
                    transcriptId = entry.arguments?.getString("transcriptId").orEmpty(),
                )
            }
        }
    }
}
