package xyz.imlazy.smsingest.setup

import android.Manifest
import android.app.Application
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.core.app.ApplicationProvider
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowApplication
import xyz.imlazy.smsingest.crypto.KeysetVerification
import xyz.imlazy.smsingest.crypto.KeysetVerifier
import xyz.imlazy.smsingest.data.PendingBatchDao
import xyz.imlazy.smsingest.data.PendingBatchEntity
import xyz.imlazy.smsingest.data.PendingBatchStatus
import xyz.imlazy.smsingest.data.UploadedDedupeDao
import xyz.imlazy.smsingest.data.UploadedDedupeIdEntity
import xyz.imlazy.smsingest.debug.SyncStatusViewModel
import xyz.imlazy.smsingest.sync.SyncScheduler

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

/** Minimal no-op [PendingBatchDao] — [SyncStatusViewModel]'s data is never rendered on the permission step. */
private class FakePermissionPendingBatchDao : PendingBatchDao {
    override suspend fun insert(batch: PendingBatchEntity) = Unit
    override suspend fun update(batch: PendingBatchEntity) = Unit
    override suspend fun delete(batch: PendingBatchEntity) = Unit
    override suspend fun getByClientBatchId(clientBatchId: String): PendingBatchEntity? = null
    override fun observeByState(state: String): Flow<List<PendingBatchEntity>> = flowOf(emptyList())
    override suspend fun getByState(state: String): List<PendingBatchEntity> = emptyList()
    override suspend fun deleteOversized(maxChars: Int): Int = 0
    override fun observeCountByState(state: String): Flow<Int> = flowOf(0)
    override fun observeMostRecentStatus(): Flow<PendingBatchStatus?> = flowOf(null)
}

/** Minimal no-op [UploadedDedupeDao] — same rationale as [FakePermissionPendingBatchDao]. */
private class FakePermissionUploadedDedupeDao : UploadedDedupeDao {
    override suspend fun insert(entry: UploadedDedupeIdEntity) = Unit
    override suspend fun exists(dedupeId: String): Boolean = false
    override fun observeCount(): Flow<Int> = flowOf(0)
}

/**
 * Robolectric + Compose-test-rule coverage for the permission-consent screen
 * (`SetupScreen.kt`'s private `PermissionRequestContent`, reached via
 * `SetupStep.PermissionRequest`). Closes the "Permission flow on Android 15
 * (grant, deny, re-request)" gap noted in the plan's Test Plan section.
 *
 * The interactive tap-through-grant case (driving
 * `ActivityResultContracts.RequestMultiplePermissions()`'s callback via a
 * simulated system permission dialog result) is deliberately not covered
 * here — see the class doc on why, at the bottom of this file's test list.
 *
 * `@Config(application = ...)` substitutes the stock [android.app.Application]
 * for the manifest's [xyz.imlazy.smsingest.SmsIngestApplication] — without it,
 * Robolectric runs that real `onCreate()` before `@Before`, which forces
 * `SyncScheduler.ensurePeriodicSync()` (`WorkManager.getInstance(...)`) via a
 * real `AppContainer` and then collides with this test's own
 * `WorkManagerTestInitHelper.initializeTestWorkManager()` call below
 * (`IllegalStateException: WorkManager is already initialized`). See
 * `SyncSchedulerTest`'s class doc, which found and fixed this first.
 */
@RunWith(RobolectricTestRunner::class)
@Config(application = android.app.Application::class)
class SetupScreenPermissionTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Before
    fun setUp() {
        // SyncScheduler's constructor calls WorkManager.getInstance(context) directly
        // (not through androidx.startup here), so the test WorkManager instance must
        // be initialized explicitly before anything in this test constructs one.
        WorkManagerTestInitHelper.initializeTestWorkManager(ApplicationProvider.getApplicationContext())
    }

    private fun statusViewModel(): SyncStatusViewModel {
        val context = ApplicationProvider.getApplicationContext<Application>()
        return SyncStatusViewModel(
            FakePermissionPendingBatchDao(),
            FakePermissionUploadedDedupeDao(),
            SyncScheduler(context),
        )
    }

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
        val viewModel = SetupViewModel(FakePermissionCredentialStore(), FakePermissionKeysetVerifier())
        val statusVm = statusViewModel()

        // NOTE: once `onPermissionsGranted()` fires below, `SetupScreen`'s own `when`
        // recomposes into `QrScanScreen`, which touches CameraX
        // (`ProcessCameraProvider.getInstance`) synchronously inside an `AndroidView`
        // factory during composition. That path was not independently verified under
        // Robolectric (no camera shadow/testing artifact is on this project's test
        // classpath) — if it turns out to be unsafe here, this test is the one that
        // will surface it, and the fix is a Robolectric camera shadow or an
        // `@Config`-level camera stub, not a change to the assertion below.
        composeTestRule.setContent {
            SetupScreen(viewModel = viewModel, statusViewModel = statusVm)
        }
        composeTestRule.waitForIdle()

        assertEquals(SetupStep.QrScan, viewModel.step.value)
    }

    @Test
    fun `shows consent content and does not advance when permissions are not yet granted`() {
        // No shadow grant here — Robolectric denies runtime permissions by default.
        val viewModel = SetupViewModel(FakePermissionCredentialStore(), FakePermissionKeysetVerifier())
        val statusVm = statusViewModel()

        composeTestRule.setContent {
            SetupScreen(viewModel = viewModel, statusViewModel = statusVm)
        }
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Grant permissions").assertExists()
        composeTestRule.onNodeWithText("Set up SMS Ingest").assertExists()
        assertEquals(SetupStep.PermissionRequest, viewModel.step.value)
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
