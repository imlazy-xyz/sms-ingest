package xyz.imlazy.smsingest.setup

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import xyz.imlazy.smsingest.crypto.KeysetVerification
import xyz.imlazy.smsingest.crypto.KeysetVerifier

/**
 * Setup flow steps, in order: permission consent, QR scan, keyset verification,
 * then done (or a retryable scan/verification error).
 */
sealed interface SetupStep {
    data object PermissionRequest : SetupStep
    data object QrScan : SetupStep
    data object VerifyingKeyset : SetupStep
    data class ScanError(val message: String) : SetupStep
    data object Complete : SetupStep
}

class SetupViewModel(
    private val credentialStore: CredentialStore,
    private val keysetVerifier: KeysetVerifier,
) : ViewModel() {

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
            onSuccess = { payload -> verifyThenSave(payload) },
            onFailure = { error ->
                _step.value = SetupStep.ScanError(error.message ?: "invalid provisioning QR code")
            },
        )
    }

    /**
     * Fetch the backend keyset and confirm its fingerprint matches the QR pin
     * before persisting anything, so setup fails on a keyset that does not match
     * the pin instead of silently trusting it.
     */
    private fun verifyThenSave(payload: ProvisioningPayload) {
        _step.value = SetupStep.VerifyingKeyset
        viewModelScope.launch {
            val result = keysetVerifier.verify(payload.apiBaseUrl, payload.serverKeyPin)
            _step.value = when (result) {
                is KeysetVerification.Verified -> {
                    credentialStore.save(payload, result.publicKeysetJson)
                    SetupStep.Complete
                }
                KeysetVerification.PinMismatch ->
                    SetupStep.ScanError("server key does not match the provisioning code")
                is KeysetVerification.Unavailable ->
                    SetupStep.ScanError("could not reach the server to verify its key")
            }
        }
    }

    fun retryScan() {
        _step.value = SetupStep.QrScan
    }

    companion object {
        fun factory(
            credentialStore: CredentialStore,
            keysetVerifier: KeysetVerifier,
        ): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    SetupViewModel(credentialStore, keysetVerifier) as T
            }
    }
}
