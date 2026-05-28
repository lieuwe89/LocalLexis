package app.locallexis.data.pairing

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * QR-code payload v1. Produced by the hub UI when minting a pairing
 * token; scanned by the device and decoded with [parse]. Field names
 * match the hub side's JSON exactly.
 */
@Serializable
data class PairingPayloadV1(
    @SerialName("hub_url") val hubUrl: String,
    @SerialName("workspace_id") val workspaceId: String,
    @SerialName("token") val token: String,
    @SerialName("tls_spki_b64") val tlsSpkiB64: String? = null,
) {
    init {
        if (hubUrl.isBlank()) throw PairingPayloadException("hub_url is blank")
        if (workspaceId.isBlank()) throw PairingPayloadException("workspace_id is blank")
        if (token.isBlank()) throw PairingPayloadException("token is blank")
        if (!hubUrl.startsWith("http://") && !hubUrl.startsWith("https://")) {
            throw PairingPayloadException("hub_url must use http:// or https://")
        }
    }

    companion object {
        private val JSON = Json { ignoreUnknownKeys = true }

        fun parse(payload: String): PairingPayloadV1 = try {
            JSON.decodeFromString<PairingPayloadV1>(payload)
        } catch (e: PairingPayloadException) {
            throw e
        } catch (e: Throwable) {
            throw PairingPayloadException("invalid pairing payload: ${e.message}")
        }
    }
}

class PairingPayloadException(message: String) : RuntimeException(message)
