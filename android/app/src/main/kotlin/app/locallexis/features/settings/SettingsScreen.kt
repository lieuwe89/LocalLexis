package app.locallexis.features.settings

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.locallexis.appGraph
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.settings.SettingsUiState
import app.locallexis.ui.settings.SettingsViewModelHolder
import app.locallexis.ui.settings.SyncStatus
import app.locallexis.ui.update.UpdateChecker
import app.locallexis.ui.update.UpdateInfo

@Composable
fun SettingsScreen() {
    val context = LocalContext.current
    val graph = remember(context) { context.appGraph }
    val holder: SettingsViewModelHolder =
        viewModel(factory = SettingsViewModelHolder.factory(graph))
    val state by holder.vm.state.collectAsState()
    val version = remember(context) { appVersion(context) }
    val uriHandler = LocalUriHandler.current
    var update by remember { mutableStateOf<UpdateInfo?>(null) }

    LaunchedEffect(Unit) {
        holder.vm.refresh()
        update = UpdateChecker().check(rawVersion(context))
    }

    SettingsContent(
        state = state,
        appVersion = version,
        onSync = holder.vm::syncNow,
        onUnpair = holder.vm::unpair,
        update = update,
        onDownloadUpdate = { update?.let { uriHandler.openUri(it.releaseUrl) } },
    )
}

@Composable
fun SettingsContent(
    state: SettingsUiState,
    appVersion: String,
    onSync: () -> Unit,
    onUnpair: () -> Unit,
    update: UpdateInfo? = null,
    onDownloadUpdate: () -> Unit = {},
) {
    var confirmUnpair by remember { mutableStateOf(false) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)

        Section("Hub") {
            if (state.paired) {
                Field("Address", state.hubUrl ?: "—")
                Field("Workspace", state.workspaceId ?: "—")
                Field("Transport", if (state.tlsPinned) "HTTPS (pinned)" else "HTTP (LAN)")
                Field("Device", state.deviceId ?: "—")
            } else {
                Text(
                    "Not paired. Open the Pair tab to connect to a hub.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                )
            }
        }

        if (state.paired) {
            Section("Sync") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Button(
                        onClick = onSync,
                        enabled = state.sync != SyncStatus.Running,
                    ) {
                        Text("Sync now")
                    }
                    SyncStatusLabel(
                        state.sync,
                        modifier = Modifier.padding(start = 12.dp),
                    )
                }
            }

            Section("Pairing") {
                OutlinedButton(onClick = { confirmUnpair = true }) {
                    Text("Unpair this device")
                }
                Text(
                    "Removes the workspace key and hub address from this device. "
                        + "Your hub keeps its data; you can re-pair anytime.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        }

        if (update != null) {
            Section("Updates") {
                Text(
                    "Version ${update.version} is available.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Button(onClick = onDownloadUpdate, modifier = Modifier.padding(top = 8.dp)) {
                    Text("Download")
                }
            }
        }

        Text(
            "LocalLexis $appVersion",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
            modifier = Modifier.padding(top = 24.dp),
        )
    }

    if (confirmUnpair) {
        AlertDialog(
            onDismissRequest = { confirmUnpair = false },
            title = { Text("Unpair this device?") },
            text = { Text("The workspace key and hub address will be erased from this phone.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmUnpair = false
                    onUnpair()
                }) { Text("Unpair") }
            },
            dismissButton = {
                TextButton(onClick = { confirmUnpair = false }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun SyncStatusLabel(status: SyncStatus, modifier: Modifier = Modifier) {
    when (status) {
        is SyncStatus.Idle -> Unit
        is SyncStatus.Running ->
            CircularProgressIndicator(modifier = modifier.padding(4.dp))
        is SyncStatus.Success ->
            Text("Up to date", style = MaterialTheme.typography.bodyMedium, modifier = modifier)
        is SyncStatus.Failed ->
            Text(
                status.message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
                modifier = modifier,
            )
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(top = 20.dp)) {
        Text(
            title.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.primary,
        )
        HorizontalDivider(Modifier.padding(top = 4.dp, bottom = 8.dp))
        content()
    }
}

@Composable
private fun Field(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}

private fun appVersion(context: Context): String = try {
    val info = context.packageManager.getPackageInfo(context.packageName, 0)
    "v${info.versionName}"
} catch (_: Exception) {
    ""
}

private fun rawVersion(context: Context): String = try {
    context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0"
} catch (_: Exception) {
    "0"
}

@Preview(showBackground = true)
@Composable
private fun SettingsPairedPreview() {
    LocalLexisTheme {
        SettingsContent(
            state = SettingsUiState(
                paired = true,
                hubUrl = "https://192.168.1.50:8443",
                workspaceId = "ws_a1b2",
                tlsPinned = true,
                deviceId = "dev-9f3c",
                sync = SyncStatus.Success,
            ),
            appVersion = "v0.9.0",
            onSync = {},
            onUnpair = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun SettingsUnpairedPreview() {
    LocalLexisTheme {
        SettingsContent(
            state = SettingsUiState(false, null, null, false, null, SyncStatus.Idle),
            appVersion = "v0.9.0",
            onSync = {},
            onUnpair = {},
        )
    }
}
