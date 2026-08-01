package xyz.imlazy.smsingest.sync

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import xyz.imlazy.smsingest.sms.SmsRecord

/**
 * `device` block of the plaintext envelope, per
 * `projects/sms-ingest/docs/backend-plan.md` § Upload API. Descriptive only —
 * the backend does not validate it (`backend/app/services/ingestion.py`
 * reads only `messages`).
 */
@Serializable
data class DeviceInfo(
    @SerialName("app_instance_id") val appInstanceId: String,
    @SerialName("android_sdk") val androidSdk: Int,
    @SerialName("app_version") val appVersion: String,
)

/**
 * Plaintext JSON HPKE-encrypted into `UploadBatchRequest.ciphertext`, per
 * `projects/sms-ingest/docs/backend-plan.md` § Upload API "Plaintext JSON
 * before encryption".
 *
 * [schemaVersion] has no default value, for the same reason as
 * `network/UploadModels.kt`'s `UploadContextInfo.payloadType` and
 * `sms/SmsRecord.kt`'s `direction`: `kotlinx.serialization` drops
 * default-valued properties unless `encodeDefaults` is set, which would
 * silently omit this field. Callers always pass [SCHEMA_VERSION] explicitly.
 */
@Serializable
data class BatchPayload(
    @SerialName("schema_version") val schemaVersion: Int,
    val device: DeviceInfo,
    val messages: List<SmsRecord>,
) {
    companion object {
        const val SCHEMA_VERSION = 1
    }
}
