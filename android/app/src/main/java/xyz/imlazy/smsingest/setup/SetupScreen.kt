package xyz.imlazy.smsingest.setup

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat

private val REQUIRED_PERMISSIONS = arrayOf(
    Manifest.permission.READ_SMS,
    Manifest.permission.RECEIVE_SMS,
    Manifest.permission.CAMERA,
)

/** Top-level setup flow: permission consent, then QR scan, then done. Drives [SetupViewModel]. */
@Composable
fun SetupScreen(viewModel: SetupViewModel, modifier: Modifier = Modifier) {
    val step by viewModel.step.collectAsState()

    when (val current = step) {
        SetupStep.PermissionRequest ->
            PermissionRequestContent(onPermissionsGranted = viewModel::onPermissionsGranted, modifier = modifier)

        SetupStep.QrScan ->
            QrScanScreen(onQrDetected = viewModel::onQrScanned, modifier = modifier)

        SetupStep.VerifyingKeyset ->
            VerifyingKeysetContent(modifier = modifier)

        is SetupStep.ScanError ->
            ScanErrorContent(message = current.message, onRetry = viewModel::retryScan, modifier = modifier)

        SetupStep.Complete ->
            CompleteContent(modifier = modifier)
    }
}

@Composable
private fun PermissionRequestContent(onPermissionsGranted: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { results -> if (results.values.all { it }) onPermissionsGranted() }

    LaunchedEffect(Unit) {
        val alreadyGranted = REQUIRED_PERMISSIONS.all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        }
        if (alreadyGranted) onPermissionsGranted()
    }

    CenteredColumn(modifier) {
        Text(text = "Set up SMS Ingest", style = MaterialTheme.typography.headlineSmall)
        Text(
            text = "This app reads incoming and existing text messages in your inbox and " +
                "uploads them, encrypted, to your private backend. It never reads sent " +
                "messages or other apps' data.",
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            text = "It also uses the camera once, to scan a one-time setup QR code that " +
                "connects it to your backend. The camera is not used again after setup.",
            style = MaterialTheme.typography.bodyMedium,
        )
        Button(onClick = { launcher.launch(REQUIRED_PERMISSIONS) }) {
            Text("Grant permissions")
        }
    }
}

@Composable
private fun ScanErrorContent(message: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    CenteredColumn(modifier) {
        Text(text = "Couldn't read that QR code", style = MaterialTheme.typography.headlineSmall)
        Text(text = message, style = MaterialTheme.typography.bodyMedium)
        Button(onClick = onRetry) {
            Text("Try again")
        }
    }
}

@Composable
private fun VerifyingKeysetContent(modifier: Modifier = Modifier) {
    CenteredColumn(modifier) {
        Text(text = "Verifying server key", style = MaterialTheme.typography.headlineSmall)
        Text(
            text = "Checking the backend's encryption key against the setup code.",
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun CompleteContent(modifier: Modifier = Modifier) {
    CenteredColumn(modifier) {
        Text(text = "Setup complete", style = MaterialTheme.typography.headlineSmall)
        Text(
            text = "Device provisioned. Sync isn't implemented yet.",
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun CenteredColumn(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
        content = content,
    )
}
