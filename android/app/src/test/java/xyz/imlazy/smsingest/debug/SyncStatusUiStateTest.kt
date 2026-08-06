package xyz.imlazy.smsingest.debug

import androidx.work.WorkInfo
import org.junit.Assert.assertEquals
import org.junit.Test

class SyncStatusUiStateTest {

    @Test
    fun `null state reads as not scheduled`() {
        assertEquals("not scheduled", null.toStatusLabel())
    }

    @Test
    fun `known states map to their labels`() {
        assertEquals("queued", WorkInfo.State.ENQUEUED.toStatusLabel())
        assertEquals("running", WorkInfo.State.RUNNING.toStatusLabel())
        assertEquals("succeeded", WorkInfo.State.SUCCEEDED.toStatusLabel())
        assertEquals("failed", WorkInfo.State.FAILED.toStatusLabel())
    }
}
