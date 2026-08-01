package xyz.imlazy.smsingest.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.telephony.SmsMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import xyz.imlazy.smsingest.SmsIngestApplication

/**
 * Receives `SMS_RECEIVED_ACTION` broadcasts and queues new inbox SMS via
 * [SmsIngestor]. Inbox only, per the locked v1 scope (see `open-questions.md`
 * "Decide whether to support sent SMS").
 *
 * A single broadcast can carry multiple [SmsMessage] PDUs for one long
 * (concatenated) SMS. The standard Android pattern — assumed here — is that
 * all PDUs in one broadcast share an originating address/timestamp and
 * their bodies join in sequence into one logical message, rather than being
 * treated as N separate messages.
 *
 * `onReceive` must return quickly, but queuing is a suspend/Room operation,
 * so this uses the standard `goAsync()` pattern: obtain a `PendingResult`,
 * do the work on a coroutine, then call `finish()` — otherwise the OS can
 * kill the process mid-write.
 *
 * `thread_hint`/`sim_info` aren't reliably available from the broadcast
 * intent (no SMS-provider thread id exists yet at this point in delivery;
 * the multi-SIM subscription extra is best-effort, not part of the
 * documented [Telephony] API surface) — both are left null here.
 * [SmsBackfillReader] can populate them from the provider once a message is
 * inserted there by whichever app is the default SMS handler.
 *
 * Not unit-testable in this repo (needs an instrumented test/emulator, see
 * [SmsBackfillReader]'s doc) — kept thin so manual review can cover it.
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (messages.isNullOrEmpty()) return
        val captures = toCaptures(messages, intent)
        if (captures.isEmpty()) return

        val container = (context.applicationContext as SmsIngestApplication).container
        val pendingResult = goAsync()
        receiverScope.launch {
            try {
                container.smsIngestor.enqueue(captures)
                container.syncScheduler.requestExpeditedSync()
            } finally {
                pendingResult.finish()
            }
        }
    }

    private fun toCaptures(messages: Array<SmsMessage>, intent: Intent): List<SmsCapture> {
        val first = messages.first()
        val sender = first.originatingAddress ?: return emptyList()
        val body = messages.joinToString(separator = "") { it.messageBody.orEmpty() }
        val simInfo = intent.getIntExtra(EXTRA_SUBSCRIPTION, -1).takeIf { it >= 0 }?.toString()
        return listOf(
            SmsCapture(
                sender = sender,
                body = body,
                smsReceivedAtEpochMillis = first.timestampMillis,
                threadHint = null,
                simInfo = simInfo,
            ),
        )
    }

    private companion object {
        // Undocumented but widely-relied-upon multi-SIM extra key on the
        // SMS_RECEIVED intent; no stable public constant exists for it.
        const val EXTRA_SUBSCRIPTION = "subscription"

        val receiverScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }
}
