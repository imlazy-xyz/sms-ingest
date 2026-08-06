package xyz.imlazy.smsingest.sync

import androidx.work.WorkInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkStatusAggregatorTest {

    @Test
    fun `empty list has no state`() {
        assertNull(WorkStatusAggregator.aggregate(emptyList()))
    }

    @Test
    fun `running wins over an old finished entry`() {
        val result = WorkStatusAggregator.aggregate(listOf(WorkInfo.State.SUCCEEDED, WorkInfo.State.RUNNING))
        assertEquals(WorkInfo.State.RUNNING, result)
    }

    @Test
    fun `enqueued wins over a stale failure`() {
        val result = WorkStatusAggregator.aggregate(listOf(WorkInfo.State.FAILED, WorkInfo.State.ENQUEUED))
        assertEquals(WorkInfo.State.ENQUEUED, result)
    }

    @Test
    fun `failed is surfaced ahead of an older success`() {
        val result = WorkStatusAggregator.aggregate(listOf(WorkInfo.State.SUCCEEDED, WorkInfo.State.FAILED))
        assertEquals(WorkInfo.State.FAILED, result)
    }

    @Test
    fun `a lone terminal state is reported as-is`() {
        assertEquals(WorkInfo.State.SUCCEEDED, WorkStatusAggregator.aggregate(listOf(WorkInfo.State.SUCCEEDED)))
        assertEquals(WorkInfo.State.CANCELLED, WorkStatusAggregator.aggregate(listOf(WorkInfo.State.CANCELLED)))
    }
}
