package xyz.imlazy.smsingest.sms

import android.content.Context
import android.provider.Telephony

/**
 * One-time historical inbox backfill via `content://sms/inbox`
 * ([Telephony.Sms.Inbox]). Read-only: never writes to the SMS provider.
 * When and how often this runs (once after setup, a manual retrigger, …) is
 * an orchestration decision left to whatever wires this in — this class
 * only knows how to read the inbox once, given a [Context].
 *
 * Not unit-testable in this repo: `ContentResolver` queries need
 * Robolectric or an instrumented test, neither of which this project has
 * (`projects/sms-ingest/docs/android-implementation-plan.md` — the agent
 * sandbox has no JDK/emulator either, so this couldn't be run locally at
 * all). Kept deliberately thin so manual review can cover it; the testable
 * logic (dedupe, record shape) lives in [SmsIngestor]/[SmsRecord] instead.
 */
class SmsBackfillReader(private val context: Context) {

    fun read(): List<SmsCapture> {
        val captures = mutableListOf<SmsCapture>()
        val projection = arrayOf(
            Telephony.TextBasedSmsColumns.ADDRESS,
            Telephony.TextBasedSmsColumns.BODY,
            Telephony.TextBasedSmsColumns.DATE,
            Telephony.TextBasedSmsColumns.THREAD_ID,
            Telephony.TextBasedSmsColumns.SUBSCRIPTION_ID,
        )
        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            projection,
            null,
            null,
            "${Telephony.TextBasedSmsColumns.DATE} ASC",
        )?.use { cursor ->
            val addressIndex = cursor.getColumnIndexOrThrow(Telephony.TextBasedSmsColumns.ADDRESS)
            val bodyIndex = cursor.getColumnIndexOrThrow(Telephony.TextBasedSmsColumns.BODY)
            val dateIndex = cursor.getColumnIndexOrThrow(Telephony.TextBasedSmsColumns.DATE)
            val threadIdIndex = cursor.getColumnIndexOrThrow(Telephony.TextBasedSmsColumns.THREAD_ID)
            // Not in every provider implementation, unlike the columns above — look up
            // defensively rather than assume it exists.
            val subIdIndex = cursor.getColumnIndex(Telephony.TextBasedSmsColumns.SUBSCRIPTION_ID)

            while (cursor.moveToNext()) {
                val address = cursor.getString(addressIndex) ?: continue
                val body = cursor.getString(bodyIndex) ?: continue
                val date = cursor.getLong(dateIndex)
                val threadId = if (!cursor.isNull(threadIdIndex)) cursor.getLong(threadIdIndex) else null
                val subId = if (subIdIndex >= 0 && !cursor.isNull(subIdIndex)) cursor.getInt(subIdIndex) else null

                captures += SmsCapture(
                    sender = address,
                    body = body,
                    smsReceivedAtEpochMillis = date,
                    threadHint = threadId?.toString(),
                    simInfo = subId?.toString(),
                )
            }
        }
        return captures
    }
}
