package app.locallexis.data.pairing

import app.locallexis.data.crypto.CryptoBox
import okhttp3.Interceptor
import okhttp3.RequestBody
import okhttp3.Response
import okio.Buffer
import java.io.IOException
import java.security.SecureRandom
import java.util.Base64

/**
 * OkHttp interceptor that signs every outbound request with the device's
 * Ed25519 key. Adds `X-Device-Id`, `X-Signature-B64`, `X-Timestamp`, and
 * `X-Nonce` headers, with the signature covering the same replay-protected
 * request bytes that [speechtotext.api.auth.verify_device_signature] checks
 * on the hub.
 *
 * If the device is not yet paired ([DeviceIdentityStore.getDeviceId]
 * returns null), the request is passed through unsigned. Callers that
 * need to enforce signed-only flows should gate at a higher layer.
 */
/**
 * OkHttp request tag opting a request into large-body signing (audio uploads).
 * Attach with `.tag(SignLargeBody::class.java, SignLargeBody)`. Client-side
 * only — never sent over the wire.
 */
object SignLargeBody

class SignedRequestInterceptor(
    private val cryptoBox: CryptoBox,
    private val deviceIdentityStore: DeviceIdentityStore,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val deviceId = deviceIdentityStore.getDeviceId()
            ?: return chain.proceed(chain.request())

        val request = chain.request()
        val maxBody = if (request.tag(SignLargeBody::class.java) != null) {
            MAX_UPLOAD_BODY_BYTES
        } else {
            MAX_SIGNED_BODY_BYTES
        }
        val bodyBytes = request.body.toSignedBytes(maxBody)

        val timestamp = (System.currentTimeMillis() / 1000L).toString()
        val nonce = randomNonce()
        val signature = cryptoBox.signRequest(
            method = request.method,
            path = request.url.encodedPath,
            query = request.url.encodedQuery.orEmpty(),
            timestamp = timestamp,
            nonce = nonce,
            body = bodyBytes,
        )
        val sigB64 = Base64.getEncoder().encodeToString(signature)

        val signed = request.newBuilder()
            .header("X-Device-Id", deviceId)
            .header("X-Signature-B64", sigB64)
            .header("X-Timestamp", timestamp)
            .header("X-Nonce", nonce)
            .build()

        return chain.proceed(signed)
    }

    @Throws(IOException::class)
    private fun RequestBody?.toSignedBytes(maxBytes: Long): ByteArray {
        val body = this ?: return EMPTY
        if (body.isOneShot()) {
            throw IOException("Cannot sign one-shot request body")
        }
        val length = body.contentLength()
        if (length < 0) {
            throw IOException("Cannot sign request body with unknown length")
        }
        if (length > maxBytes) {
            throw IOException(
                "Signed request body too large: $length > $maxBytes bytes",
            )
        }
        return body.let {
            Buffer().use { buf ->
                it.writeTo(buf)
                buf.readByteArray()
            }
        }
    }

    private companion object {
        val EMPTY = ByteArray(0)
        val RANDOM = SecureRandom()
        const val MAX_SIGNED_BODY_BYTES = 1_048_576L

        // Whole-file audio uploads are signed over the full body (the hub's
        // verify_device_signature covers the raw bytes), so the upload path
        // opts past the small-request cap up to the hub's own 256 MiB limit.
        const val MAX_UPLOAD_BODY_BYTES = 256L * 1024 * 1024

        fun randomNonce(): String {
            val bytes = ByteArray(16)
            RANDOM.nextBytes(bytes)
            return bytes.joinToString(separator = "") { "%02x".format(it.toInt() and 0xff) }
        }
    }
}
