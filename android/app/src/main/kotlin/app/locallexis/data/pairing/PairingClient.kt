package app.locallexis.data.pairing

import app.locallexis.data.crypto.CryptoBox
import app.locallexis.data.crypto.SealedBoxOpenException
import app.locallexis.data.crypto.WorkspaceKeyStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.Base64

/**
 * Pairing exchange against the hub's `POST /pair` endpoint.
 *
 * Wire mirror of [speechtotext.api.routes_pairing.pair_device]:
 *
 * Request  : `{token, device_pubkey_b64, device_name}`
 * Response : `{device_id, workspace_id, workspace_key_sealed_b64, lamport_observed}`
 *
 * Side effects on success: workspace key W stored in [WorkspaceKeyStore],
 * assigned device_id stored in [DeviceIdentityStore]. On any failure
 * neither store is touched.
 */
class PairingClient(
    private val cryptoBox: CryptoBox,
    private val workspaceKeyStore: WorkspaceKeyStore,
    private val deviceIdentityStore: DeviceIdentityStore,
    private val httpClient: OkHttpClient,
    private val json: Json = Json { ignoreUnknownKeys = true },
) {

    suspend fun exchange(payload: PairingPayloadV1, deviceName: String): PairingResult =
        withContext(Dispatchers.IO) {
            val pubkeyB64 = Base64.getEncoder()
                .encodeToString(cryptoBox.devicePublicKey())
            val body = json.encodeToString(
                PairRequest.serializer(),
                PairRequest(
                    token = payload.token,
                    devicePubkeyB64 = pubkeyB64,
                    deviceName = deviceName,
                ),
            )
            val url = payload.hubUrl.trimEnd('/') + "/pair"
            val request = Request.Builder()
                .url(url)
                .post(body.toRequestBody(JSON_MEDIA_TYPE))
                .build()

            val response = try {
                httpClient.newCall(request).execute()
            } catch (e: IOException) {
                throw PairingFailedException(0, "network error: ${e.message}")
            }

            response.use {
                if (!it.isSuccessful) {
                    throw PairingFailedException(it.code, "hub returned HTTP ${it.code}")
                }
                val respBody = it.body?.string()
                    ?: throw PairingFailedException(it.code, "empty response body")
                val parsed = try {
                    json.decodeFromString<PairResponse>(respBody)
                } catch (e: Throwable) {
                    throw PairingFailedException(it.code, "malformed response: ${e.message}")
                }

                val sealed = try {
                    Base64.getDecoder().decode(parsed.workspaceKeySealedB64)
                } catch (e: IllegalArgumentException) {
                    throw PairingFailedException(it.code, "workspace_key_sealed_b64 not valid base64")
                }

                val workspaceKey = try {
                    cryptoBox.openSealedBox(sealed)
                } catch (e: SealedBoxOpenException) {
                    throw PairingFailedException(it.code, "sealedbox decryption failed: ${e.message}")
                }

                workspaceKeyStore.put(workspaceKey)
                deviceIdentityStore.putDeviceId(parsed.deviceId)

                PairingResult(
                    deviceId = parsed.deviceId,
                    workspaceId = parsed.workspaceId,
                    lamportObserved = parsed.lamportObserved,
                )
            }
        }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json".toMediaType()
    }
}

data class PairingResult(
    val deviceId: String,
    val workspaceId: String,
    val lamportObserved: Long,
)

class PairingFailedException(
    val httpStatus: Int,
    message: String,
) : RuntimeException(message)

@Serializable
private data class PairRequest(
    val token: String,
    @SerialName("device_pubkey_b64") val devicePubkeyB64: String,
    @SerialName("device_name") val deviceName: String,
)

@Serializable
private data class PairResponse(
    @SerialName("device_id") val deviceId: String,
    @SerialName("workspace_id") val workspaceId: String,
    @SerialName("workspace_key_sealed_b64") val workspaceKeySealedB64: String,
    @SerialName("lamport_observed") val lamportObserved: Long,
)
