package xyz.imlazy.smsingest.setup

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

private class FakeCredentialStore(private var provisioned: Boolean = false) : CredentialStore {
    var saved: ProvisioningPayload? = null
        private set

    override fun isProvisioned(): Boolean = provisioned

    override fun save(payload: ProvisioningPayload) {
        saved = payload
        provisioned = true
    }
}

private const val VALID_QR_JSON = """
{
  "v": 1,
  "api_base_url": "https://sms-api.example.com",
  "device_id": "11111111-1111-1111-1111-111111111111",
  "device_token": "raw-token",
  "device_dedupe_secret": "raw-secret",
  "server_key_id": "server-key-2026-05",
  "server_key_pin": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "issued_at": "2026-05-23T00:00:00Z"
}
"""

class SetupViewModelTest {

    @Test
    fun `starts at permission request when no credentials are stored`() {
        val viewModel = SetupViewModel(FakeCredentialStore(provisioned = false))

        assertEquals(SetupStep.PermissionRequest, viewModel.step.value)
    }

    @Test
    fun `starts at complete when credentials are already stored`() {
        val viewModel = SetupViewModel(FakeCredentialStore(provisioned = true))

        assertEquals(SetupStep.Complete, viewModel.step.value)
    }

    @Test
    fun `advances to QR scan once permissions are granted`() {
        val viewModel = SetupViewModel(FakeCredentialStore())

        viewModel.onPermissionsGranted()

        assertEquals(SetupStep.QrScan, viewModel.step.value)
    }

    @Test
    fun `saves credentials and completes on a valid scanned payload`() {
        val credentialStore = FakeCredentialStore()
        val viewModel = SetupViewModel(credentialStore)
        viewModel.onPermissionsGranted()

        viewModel.onQrScanned(VALID_QR_JSON)

        assertEquals(SetupStep.Complete, viewModel.step.value)
        assertEquals("11111111-1111-1111-1111-111111111111", credentialStore.saved?.deviceId)
    }

    @Test
    fun `surfaces a scan error and does not save on an invalid payload`() {
        val credentialStore = FakeCredentialStore()
        val viewModel = SetupViewModel(credentialStore)
        viewModel.onPermissionsGranted()

        viewModel.onQrScanned("not json")

        assertEquals(SetupStep.ScanError::class, viewModel.step.value::class)
        assertNull(credentialStore.saved)
    }

    @Test
    fun `retryScan returns to QR scan from a scan error`() {
        val viewModel = SetupViewModel(FakeCredentialStore())
        viewModel.onPermissionsGranted()
        viewModel.onQrScanned("not json")

        viewModel.retryScan()

        assertEquals(SetupStep.QrScan, viewModel.step.value)
    }
}
