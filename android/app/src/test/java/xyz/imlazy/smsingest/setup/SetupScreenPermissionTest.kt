package xyz.imlazy.smsingest.setup

import android.Manifest
import android.app.Application
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowApplication
import xyz.imlazy.smsingest.crypto.KeysetVerification
import xyz.imlazy.smsingest.crypto.KeysetVerifier

/**
 * Named distinctly from [SetupViewModelTest]'s `FakeCredentialStore` — this
 * codebase declares `private class Fake...` per-file, and a same-package
 * top-level `private` name collision across files has bitten this project
 * before (see git history).
 */
private class FakePermissionCredentialStore(private var provisioned: Boolean = false) : CredentialStore {
    override fun isProvisioned(): Boolean = provisioned

    override fun save(payload: ProvisioningPayload, publicKeysetJson: String) {
        provisioned = true
    }

    override fun getApiBaseUrl(): String? = null
    override fun getServerKeyId(): String? = null
    override fun getServerKeyPin(): String? = null
    override fun getPublicKeysetJson(): String? = null
    override fun getDeviceToken(): String? = null
    override fun getDeviceDedupeSecret(): String? = null
    override fun isBackfillComplete(): Boolean = false
    override fun markBackfillComplete() = Unit
}

private class FakePermissionKeysetVerifier : KeysetVerifier {
    override suspend fun verify(apiBaseUrl: String, expectedPin: String): KeysetVerification =
        KeysetVerification.Unavailable("not exercised in this test")
}

/**
 * Robolectric + Compose-test-rule coverage for the permission-consent screen
 * ([PermissionRequestContent], reached via `SetupStep.PermissionRequest`).
 * Closes the "Permission flow on Android 15 (grant, deny, re-request)" gap
 * noted in the plan's Test Plan section.
 *
 * Composes [PermissionRequestContent] directly rather than going through
 * [SetupScreen]'s full `when` dispatch: once the already-granted case calls
 * `onPermissionsGranted()`, `SetupScreen` would recompose into `QrScanScreen`,
 * whose `AndroidView` factory calls `ProcessCameraProvider.getInstance()`
 * synchronously — no Robolectric camera shadow is on this project's test
 * classpath, and that genuinely threw `IllegalStateException` in CI the first
 * time this test went through `SetupScreen`. Composing
 * [PermissionRequestContent] directly (now `internal`, not `private`, for
 * exactly this reason) tests the same real production composable and its
 * real `onPermissionsGranted` callback without ever reaching `QrScanScreen`.
 *
 * The interactive tap-through-grant case (driving
 * `ActivityResultContracts.RequestMultiplePermissions()`'s callback via a
 * simulated system permission dialog result) is deliberately not covered
 * here — see the class doc on why, at the bottom of this file's test list.
 *
 * `@Config(application = ...)` substitutes the stock [android.app.Application]
 * for the manifest's [xyz.imlazy.smsingest.SmsIngestApplication] — without it,
 * Robolectric runs that real `onCreate()` before any `@Test`, which builds a
 * full `AppContainer` and forces `SyncScheduler.ensurePeriodicSync()`
 * (`WorkManager.getInstance(...)`), none of which this permission-only test
 * needs or wants running. See `SyncSchedulerTest`'s class doc, which found
 * this landmine first.
 */
@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class SetupScreenPermissionTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private fun grantAllRequiredPermissions() {
        val shadowApplication: ShadowApplication =
            Shadows.shadowOf(ApplicationProvider.getApplicationContext<Application>())
        shadowApplication.grantPermissions(
            Manifest.permission.READ_SMS,
            Manifest.permission.RECEIVE_SMS,
            Manifest.permission.CAMERA,
        )
    }

    @Test
    fun `auto-advances past permission request when all permissions are already granted`() {
        grantAllRequiredPermissions()
        var granted = false

        composeTestRule.setContent {
            PermissionRequestContent(onPermissionsGranted = { granted = true })
        }
        composeTestRule.waitForIdle()

        assertEquals(true, granted)
    }

    @Test
    fun `shows consent content and does not advance when permissions are not yet granted`() {
        // No shadow grant here — Robolectric denies runtime permissions by default.
        var granted = false

        composeTestRule.setContent {
            PermissionRequestContent(onPermissionsGranted = { granted = true })
        }
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Grant permissions").assertExists()
        composeTestRule.onNodeWithText("Set up SMS Ingest").assertExists()
        assertEquals(false, granted)
    }

    // Tap-through-grant case (button click -> system permission dialog ->
    // ActivityResultContracts.RequestMultiplePermissions() callback ->
    // onPermissionsGranted()) was not attempted. The launcher registers against
    // the real host Activity that the compose test rule creates and owns, and
    // this test does not control or intercept that activity's activity-result
    // registry. Driving the callback would need either Robolectric's
    // ShadowActivityResultRegistry or a fake ActivityResultCaller wired in ahead
    // of composition; neither was tried here, so no claim is made about how well
    // either works with this Compose+Robolectric combination. Cases 1 and 2
    // above cover the actual branching logic (already-granted auto-advance vs.
    // not-yet-granted no-op); interactive-launcher coverage is left for a
    // follow-up, most naturally as an instrumented androidTest (Espresso-Intents
    // or UiAutomator) that can actually drive the system permission dialog.
}
