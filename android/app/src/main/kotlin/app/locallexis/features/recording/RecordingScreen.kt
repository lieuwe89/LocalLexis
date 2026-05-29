package app.locallexis.features.recording

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.locallexis.appGraph
import app.locallexis.audio.RecordingController
import app.locallexis.audio.RecordingService
import app.locallexis.audio.formatElapsed
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.components.ErrorBanner

@Composable
fun RecordingScreen() {
    val context = LocalContext.current
    val graph = remember(context) { context.appGraph }
    val state by RecordingController.state.collectAsState()
    val paired = remember(state.status) { graph.hubConfig.isPaired() }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { result ->
        if (result[Manifest.permission.RECORD_AUDIO] == true || hasMic(context)) {
            RecordingService.start(context)
        }
    }

    RecordingContent(
        state = state,
        paired = paired,
        onStart = {
            if (hasMic(context)) RecordingService.start(context)
            else launcher.launch(recordingPermissions())
        },
        onStop = { RecordingService.stop(context) },
        onAck = RecordingController::acknowledge,
    )
}

@Composable
fun RecordingContent(
    state: RecordingController.UiState,
    paired: Boolean,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onAck: () -> Unit,
) {
    val active = state.status == RecordingController.Status.Recording ||
        state.status == RecordingController.Status.Paused

    Column(Modifier.fillMaxSize()) {
        if (!paired) {
            ErrorBanner("Not paired. Recordings will upload once you pair a hub.")
        }
        Column(
            Modifier.fillMaxSize().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = if (active) formatElapsed(state.elapsedMs) else "00:00",
                style = MaterialTheme.typography.displayMedium,
            )
            Text(
                text = when (state.status) {
                    RecordingController.Status.Recording -> "Recording"
                    RecordingController.Status.Paused -> "Paused (interrupted)"
                    else -> "Ready"
                },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                modifier = Modifier.padding(top = 8.dp),
            )

            if (active) {
                LinearProgressIndicator(
                    progress = { (state.amplitude / 32767f).coerceIn(0f, 1f) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 24.dp),
                )
            }

            state.message?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodyMedium,
                    textAlign = TextAlign.Center,
                    color = if (state.status == RecordingController.Status.Error) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                    modifier = Modifier.padding(top = 24.dp),
                )
            }

            if (active) {
                Button(
                    onClick = onStop,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                    ),
                    modifier = Modifier.padding(top = 32.dp),
                ) {
                    Text("Stop")
                }
            } else {
                Button(onClick = onStart, modifier = Modifier.padding(top = 32.dp)) {
                    Text("Start recording")
                }
                if (state.status == RecordingController.Status.Saved ||
                    state.status == RecordingController.Status.Error
                ) {
                    OutlinedButton(onClick = onAck, modifier = Modifier.padding(top = 8.dp)) {
                        Text("Dismiss")
                    }
                }
            }
        }
    }
}

private fun hasMic(context: Context): Boolean =
    ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
        PackageManager.PERMISSION_GRANTED

private fun recordingPermissions(): Array<String> {
    val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        perms += Manifest.permission.POST_NOTIFICATIONS
    }
    return perms.toTypedArray()
}

@Preview(showBackground = true)
@Composable
private fun RecordingIdlePreview() {
    LocalLexisTheme {
        RecordingContent(RecordingController.UiState(), paired = true, {}, {}, {})
    }
}

@Preview(showBackground = true)
@Composable
private fun RecordingActivePreview() {
    LocalLexisTheme {
        RecordingContent(
            RecordingController.UiState(
                status = RecordingController.Status.Recording,
                elapsedMs = 95_000,
                amplitude = 12_000,
            ),
            paired = true,
            {}, {}, {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun RecordingUnpairedPreview() {
    LocalLexisTheme {
        RecordingContent(RecordingController.UiState(), paired = false, {}, {}, {})
    }
}
