package app.locallexis.data.pairing

import app.locallexis.data.crypto.CryptoBox
import okhttp3.Interceptor
import okhttp3.Response
import okio.Buffer
import java.util.Base64

/**
 * OkHttp interceptor that signs every outbound request with the device's
 * Ed25519 key. Adds `X-Device-Id` and `X-Signature-B64` headers, with
 * the signature covering `METHOD + "\n" + PATH + "\n" + BODY` — exactly
 * what [speechtotext.api.auth.verify_device_signature] checks on the
 * hub.
 *
 * If the device is not yet paired ([DeviceIdentityStore.getDeviceId]
 * returns null), the request is passed through unsigned. Callers that
 * need to enforce signed-only flows should gate at a higher layer.
 */
class SignedRequestInterceptor(
    private val cryptoBox: CryptoBox,
    private val deviceIdentityStore: DeviceIdentityStore,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val deviceId = deviceIdentityStore.getDeviceId()
            ?: return chain.proceed(chain.request())

        val request = chain.request()
        val bodyBytes = request.body?.let { body ->
            Buffer().use { buf ->
                body.writeTo(buf)
                buf.readByteArray()
            }
        } ?: EMPTY

        val signature = cryptoBox.signRequest(
            method = request.method,
            path = request.url.encodedPath,
            body = bodyBytes,
        )
        val sigB64 = Base64.getEncoder().encodeToString(signature)

        val signed = request.newBuilder()
            .header("X-Device-Id", deviceId)
            .header("X-Signature-B64", sigB64)
            .build()

        return chain.proceed(signed)
    }

    private companion object {
        val EMPTY = ByteArray(0)
    }
}
