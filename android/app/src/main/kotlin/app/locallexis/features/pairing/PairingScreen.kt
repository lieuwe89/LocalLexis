package app.locallexis.features.pairing

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import app.locallexis.appGraph
import app.locallexis.data.pairing.PairingPayloadV1
import app.locallexis.ui.components.CenteredMessage
import app.locallexis.ui.components.ErrorBanner
import app.locallexis.ui.pairing.PairingUiState
import app.locallexis.ui.pairing.PairingViewModelHolder
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

@Composable
fun PairingScreen() {
    val context = LocalContext.current
    val graph = remember(context) { context.appGraph }
    val holder: PairingViewModelHolder =
        viewModel(factory = PairingViewModelHolder.factory(graph))
    val state by holder.vm.uiState.collectAsState()
    val deviceName = remember { Build.MODEL?.takeIf { it.isNotBlank() } ?: "Android device" }

    PairingContent(
        state = state,
        deviceName = deviceName,
        pairedHubUrl = graph.hubConfig.getHubUrl(),
        pairedWorkspaceId = graph.hubConfig.getWorkspaceId(),
        onSubmit = holder.vm::submit,
        onReset = holder.vm::reset,
    )
}

@Composable
private fun PairingContent(
    state: PairingUiState,
    deviceName: String,
    pairedHubUrl: String?,
    pairedWorkspaceId: String?,
    onSubmit: (PairingPayloadV1, String) -> Unit,
    onReset: () -> Unit,
) {
    when (state) {
        is PairingUiState.Exchanging ->
            LabeledProgress("Pairing with ${state.payload.hubUrl}…")

        is PairingUiState.Paired -> PairedSuccess(state, onDone = onReset)

        is PairingUiState.Error -> {
            val msg = if (state.httpStatus > 0) {
                "Pairing failed (HTTP ${state.httpStatus}): ${state.message}"
            } else {
                "Pairing failed: ${state.message}"
            }
            CenteredMessage(msg, onRetry = onReset)
        }

        is PairingUiState.Idle -> {
            var rescanning by rememberSaveable { mutableStateOf(false) }
            if (pairedHubUrl != null && !rescanning) {
                AlreadyPaired(pairedHubUrl, pairedWorkspaceId) { rescanning = true }
            } else {
                ScanOrEnter(deviceName = deviceName, onSubmit = onSubmit)
            }
        }
    }
}

@Composable
private fun ScanOrEnter(
    deviceName: String,
    onSubmit: (PairingPayloadV1, String) -> Unit,
) {
    val context = LocalContext.current
    var cameraGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> cameraGranted = granted }

    LaunchedEffect(Unit) {
        if (!cameraGranted) permLauncher.launch(Manifest.permission.CAMERA)
    }

    var parseError by remember { mutableStateOf<String?>(null) }
    var showManual by rememberSaveable { mutableStateOf(false) }
    var manualText by rememberSaveable { mutableStateOf("") }

    val submitRaw: (String) -> Unit = { raw ->
        qrToPayload(raw).fold(
            onSuccess = { parseError = null; onSubmit(it, deviceName) },
            onFailure = { parseError = it.message ?: "Invalid pairing code" },
        )
    }

    val manualVisible = showManual || !cameraGranted

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Pair this device", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Scan the QR code from the desktop hub (Settings to pair a device).",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp),
        )

        if (cameraGranted && !showManual) {
            QrScanner(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .clip(RoundedCornerShape(12.dp)),
                onCode = submitRaw,
            )
        } else if (!cameraGranted) {
            Text(
                "Camera permission is off. Grant it to scan, or paste the code below.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            )
            TextButton(onClick = { permLauncher.launch(Manifest.permission.CAMERA) }) {
                Text("Grant camera access")
            }
        }

        parseError?.let { ErrorBanner(it) }

        if (cameraGranted) {
            TextButton(onClick = { showManual = !showManual }) {
                Text(if (showManual) "Use camera instead" else "Enter code manually")
            }
        }

        if (manualVisible) {
            OutlinedTextField(
                value = manualText,
                onValueChange = { manualText = it },
                label = { Text("Pairing code (JSON)") },
                minLines = 3,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { submitRaw(manualText) },
                enabled = manualText.isNotBlank(),
                modifier = Modifier.padding(top = 8.dp),
            ) {
                Text("Pair")
            }
        }
    }
}

/**
 * CameraX preview bound to an ML Kit QR analyzer. Fires [onCode] at most once
 * (guarded by [AtomicBoolean]); the host swaps this composable out on the next
 * state, which unbinds the camera via the lifecycle.
 */
@Composable
private fun QrScanner(
    onCode: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val handled = remember { AtomicBoolean(false) }
    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember {
        BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build(),
        )
    }

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            val previewView = PreviewView(ctx)
            val providerFuture = ProcessCameraProvider.getInstance(ctx)
            providerFuture.addListener({
                val provider = providerFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(analysisExecutor) { proxy ->
                    scanFrame(scanner, proxy, handled, onCode)
                }
                provider.unbindAll()
                provider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis,
                )
            }, ContextCompat.getMainExecutor(ctx))
            previewView
        },
    )
}

@SuppressLint("UnsafeOptInUsageError")
private fun scanFrame(
    scanner: BarcodeScanner,
    proxy: ImageProxy,
    handled: AtomicBoolean,
    onCode: (String) -> Unit,
) {
    val media = proxy.image
    if (media == null) {
        proxy.close()
        return
    }
    val image = InputImage.fromMediaImage(media, proxy.imageInfo.rotationDegrees)
    scanner.process(image)
        .addOnSuccessListener { barcodes ->
            val raw = barcodes.firstOrNull { it.format == Barcode.FORMAT_QR_CODE }?.rawValue
            if (raw != null && handled.compareAndSet(false, true)) {
                onCode(raw)
            }
        }
        .addOnCompleteListener { proxy.close() }
}

@Composable
private fun LabeledProgress(label: String) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator()
        Text(label, modifier = Modifier.padding(top = 16.dp), textAlign = TextAlign.Center)
    }
}

@Composable
private fun PairedSuccess(state: PairingUiState.Paired, onDone: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            Icons.Filled.CheckCircle,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Text(
            "Paired",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(top = 12.dp),
        )
        Text(
            "Workspace ${state.workspaceId}\nDevice ${state.deviceId}",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 4.dp),
        )
        TextButton(onClick = onDone, modifier = Modifier.padding(top = 16.dp)) {
            Text("Done")
        }
    }
}

@Composable
private fun AlreadyPaired(hubUrl: String, workspaceId: String?, onRepair: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            Icons.Filled.CheckCircle,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Text(
            "Paired",
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(top = 12.dp),
        )
        Text(
            hubUrl + (workspaceId?.let { "\nWorkspace $it" } ?: ""),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 4.dp),
        )
        TextButton(onClick = onRepair, modifier = Modifier.padding(top = 16.dp)) {
            Text("Pair a different hub")
        }
    }
}
