package xyz.imlazy.smsingest.debug

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Testing-phase debugging panel shown on the setup-complete screen
 * ([xyz.imlazy.smsingest.setup.SetupScreen]'s `CompleteContent`): live
 * queue counts, last sync attempt/error, and WorkManager state per worker,
 * plus manual "Sync now"/"Force backfill" triggers. Deliberately shown
 * unconditionally (not gated behind a debug build) since the only install
 * path exercised so far is the CI-signed release APK — see
 * `android-release.yml` and `handoff.md`.
 */
@Composable
fun SyncStatusScreen(viewModel: SyncStatusViewModel, modifier: Modifier = Modifier) {
    val state by viewModel.uiState.collectAsState()

    Column(
        modifier = modifier.fillMaxWidth().padding(top = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        HorizontalDivider()
        Text(text = "Sync status", style = MaterialTheme.typography.titleMedium)
        Text(text = "Pending: ${state.pendingCount}    Uploaded: ${state.uploadedCount}")
        Text(text = "Last attempt: ${formatTimestamp(state.lastAttemptAtEpochMillis)}")
        Text(text = "Last attempt result: ${state.lastAttemptState ?: "none yet"}")
        if (state.lastError != null) {
            Text(
                text = "Last error: ${state.lastError} (retry #${state.lastRetryCount})",
                color = MaterialTheme.colorScheme.error,
            )
        }
        Text(text = "Periodic sync worker: ${state.periodicSyncState.toStatusLabel()}")
        Text(text = "Expedited sync worker: ${state.expeditedSyncState.toStatusLabel()}")
        Text(text = "Backfill worker: ${state.backfillState.toStatusLabel()}")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = viewModel::syncNow) { Text("Sync now") }
            Button(onClick = viewModel::forceBackfill) { Text("Force backfill") }
        }
    }
}

private fun formatTimestamp(epochMillis: Long?): String {
    if (epochMillis == null) return "never"
    return DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
        .withZone(ZoneId.systemDefault())
        .format(Instant.ofEpochMilli(epochMillis))
}
