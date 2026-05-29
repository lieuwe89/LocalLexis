package app.locallexis.features.pairing

import app.locallexis.data.pairing.PairingPayloadV1

/**
 * Decode a scanned (or pasted) QR string into a [PairingPayloadV1], capturing
 * any [app.locallexis.data.pairing.PairingPayloadException] as a failed
 * [Result] instead of throwing. Shared by the camera analyzer and the
 * manual-entry fallback so both reach the view model the same way.
 */
fun qrToPayload(raw: String): Result<PairingPayloadV1> = runCatching {
    PairingPayloadV1.parse(raw.trim())
}
