package app.locallexis.data.http

import okhttp3.OkHttpClient
import java.net.URI
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Derives an OkHttp client that talks to a LocalLexis hub over a pinned
 * connection.
 *
 * The hub serves a self-signed cert whose SAN covers only localhost /
 * 127.0.0.1 / 0.0.0.0 (see speechtotext.api.tls), never its LAN IP. A phone
 * reaching `https://<lan-ip>:port` therefore fails both the default CA check
 * (the cert chains to no system root) and hostname verification (the IP is
 * not in the SAN). The pairing QR instead carries the cert's SPKI pin —
 * base64(SHA-256(SubjectPublicKeyInfo)) — and that pin is the sole trust
 * anchor: [SpkiPinningTrustManager] trusts the connection iff the presented
 * leaf's SPKI digest equals the pin, and hostname verification is waived.
 *
 * The pinning trust manager is ONLY ever installed when a pin is present. For
 * plain http, or https with no/malformed pin, the [base] client is returned
 * unchanged so the platform's secure defaults apply — an unpinned self-signed
 * https hub is then correctly rejected, and the user must pair from a QR that
 * carries the pin.
 */
object HubTls {

    /**
     * @param base the app-scoped client (carries the signing interceptor).
     * @param hubUrl the hub base URL the client will call.
     * @param spkiB64 the hub's SPKI pin body, or null for plain-http hubs.
     */
    fun pinnedClient(base: OkHttpClient, hubUrl: String, spkiB64: String?): OkHttpClient {
        val pin = spkiB64?.takeIf { it.isNotBlank() } ?: return base
        if (!hubUrl.startsWith("https://", ignoreCase = true)) return base
        hostOf(hubUrl) ?: return base

        val expectedDigest = try {
            Base64.getDecoder().decode(pin.trim())
        } catch (_: IllegalArgumentException) {
            return base // malformed pin: secure default rejects the self-signed hub
        }

        val trustManager = SpkiPinningTrustManager(expectedDigest)
        val sslContext = SSLContext.getInstance("TLS").apply {
            init(null, arrayOf<TrustManager>(trustManager), SecureRandom())
        }
        return base.newBuilder()
            .sslSocketFactory(sslContext.socketFactory, trustManager)
            .hostnameVerifier { _, _ -> true }
            .build()
    }

    private fun hostOf(url: String): String? = try {
        URI(url).host
    } catch (_: Exception) {
        null
    }
}

/**
 * Trusts a server cert iff SHA-256 of its SubjectPublicKeyInfo equals the
 * pinned digest from the pairing QR. The pin is the only check: CA chaining,
 * hostname, and expiry are deliberately ignored because the hub's self-signed
 * cert chains to no root and its SAN omits the LAN IP. Replacing the trust
 * manager (rather than adding an OkHttp CertificatePinner) avoids OkHttp's
 * chain-cleaning step, which needs trust anchors we do not have.
 */
private class SpkiPinningTrustManager(
    private val expectedDigest: ByteArray,
) : X509TrustManager {

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val leaf = chain?.firstOrNull()
            ?: throw CertificateException("empty certificate chain")
        val actual = MessageDigest.getInstance("SHA-256").digest(leaf.publicKey.encoded)
        if (!MessageDigest.isEqual(actual, expectedDigest)) {
            throw CertificateException("hub SPKI pin mismatch")
        }
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}
