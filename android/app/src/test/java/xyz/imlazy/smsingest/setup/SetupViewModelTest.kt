package xyz.imlazy.smsingest.setup

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import xyz.imlazy.smsingest.crypto.KeysetVerification
import xyz.imlazy.smsingest.crypto.KeysetVerifier

private class FakeCredentialStore(private var provisioned: Boolean = false) : CredentialStore {
    var saved: ProvisioningPayload? = null
        private set

    override fun isProvisioned(): Boolean = provisioned

    override fun save(payload: ProvisioningPayload) {
        saved = payload
        provisioned = true
    }

    override fun getApiBaseUrl(): String? = saved?.apiBaseUrl
    override fun getServerKeyId(): String? = saved?.serverKeyId
    override fun getServerKeyPin(): String? = saved?.serverKeyPin
}

/** Verifier stub returning a fixed outcome; never touches the network. */
private class FakeKeysetVerifier(private val result: KeysetVerification) : KeysetVerifier {
    override suspend fun verify(apiBaseUrl: String, expectedPin: String): KeysetVerification = result
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

@OptIn(ExperimentalCoroutinesApi::class)
class SetupViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(
        credentialStore: CredentialStore,
        verification: KeysetVerification = KeysetVerification.Verified("public-keyset-json"),
    ) = SetupViewModel(credentialStore, FakeKeysetVerifier(verification))

    @Test
    fun `starts at permission request when no credentials are stored`() {
        val vm = viewModel(FakeCredentialStore(provisioned = false))
        assertEquals(SetupStep.PermissionRequest, vm.step.value)
    }

    @Test
    fun `starts at complete when credentials are already stored`() {
        val vm = viewModel(FakeCredentialStore(provisioned = true))
        assertEquals(SetupStep.Complete, vm.step.value)
    }

    @Test
    fun `advances to QR scan once permissions are granted`() {
        val vm = viewModel(FakeCredentialStore())
        vm.onPermissionsGranted()
        assertEquals(SetupStep.QrScan, vm.step.value)
    }

    @Test
    fun `verifies then saves and completes on a valid payload with matching keyset`() =
        runTest(dispatcher) {
            val credentialStore = FakeCredentialStore()
            val vm = viewModel(credentialStore, KeysetVerification.Verified("public-keyset-json"))
            vm.onPermissionsGranted()

            vm.onQrScanned(VALID_QR_JSON)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(SetupStep.Complete, vm.step.value)
            assertEquals("11111111-1111-1111-1111-111111111111", credentialStore.saved?.deviceId)
        }

    @Test
    fun `errors and does not save when the fetched keyset pin does not match`() =
        runTest(dispatcher) {
            val credentialStore = FakeCredentialStore()
            val vm = viewModel(credentialStore, KeysetVerification.PinMismatch)
            vm.onPermissionsGranted()

            vm.onQrScanned(VALID_QR_JSON)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(SetupStep.ScanError::class, vm.step.value::class)
            assertNull(credentialStore.saved)
        }

    @Test
    fun `errors and does not save when the server is unreachable`() =
        runTest(dispatcher) {
            val credentialStore = FakeCredentialStore()
            val vm = viewModel(credentialStore, KeysetVerification.Unavailable("IOException"))
            vm.onPermissionsGranted()

            vm.onQrScanned(VALID_QR_JSON)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(SetupStep.ScanError::class, vm.step.value::class)
            assertNull(credentialStore.saved)
        }

    @Test
    fun `surfaces a scan error and does not save on a malformed payload`() {
        val credentialStore = FakeCredentialStore()
        val vm = viewModel(credentialStore)
        vm.onPermissionsGranted()

        vm.onQrScanned("not json")

        assertEquals(SetupStep.ScanError::class, vm.step.value::class)
        assertNull(credentialStore.saved)
    }

    @Test
    fun `retryScan returns to QR scan from a scan error`() {
        val vm = viewModel(FakeCredentialStore())
        vm.onPermissionsGranted()
        vm.onQrScanned("not json")

        vm.retryScan()

        assertEquals(SetupStep.QrScan, vm.step.value)
    }
}
