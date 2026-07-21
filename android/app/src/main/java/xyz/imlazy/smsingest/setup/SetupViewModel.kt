package xyz.imlazy.smsingest.setup

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Setup flow steps, in order: permission consent, QR scan, then done (or a retryable scan error). */
sealed interface SetupStep {
    data object PermissionRequest : SetupStep
    data object QrScan : SetupStep
    data class ScanError(val message: String) : SetupStep
    data object Complete : SetupStep
}

class SetupViewModel(private val credentialStore: CredentialStore) : ViewModel() {

    private val _step = MutableStateFlow<SetupStep>(
        if (credentialStore.isProvisioned()) SetupStep.Complete else SetupStep.PermissionRequest,
    )
    val step: StateFlow<SetupStep> = _step.asStateFlow()

    fun onPermissionsGranted() {
        if (_step.value == SetupStep.PermissionRequest) {
            _step.value = SetupStep.QrScan
        }
    }

    /** Called with the raw scanned QR text. Never logged — see ProvisioningPayloadParser. */
    fun onQrScanned(rawPayload: String) {
        ProvisioningPayloadParser.parse(rawPayload).fold(
            onSuccess = { payload ->
                credentialStore.save(payload)
                _step.value = SetupStep.Complete
            },
            onFailure = { error ->
                _step.value = SetupStep.ScanError(error.message ?: "invalid provisioning QR code")
            },
        )
    }

    fun retryScan() {
        _step.value = SetupStep.QrScan
    }

    companion object {
        fun factory(credentialStore: CredentialStore): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    SetupViewModel(credentialStore) as T
            }
    }
}
