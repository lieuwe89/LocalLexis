package app.locallexis.data.http

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test
import java.security.MessageDigest
import java.util.Base64
import javax.net.ssl.SSLException

/**
 * Proves the pin — not CA trust or hostname matching — is the gate. The
 * server presents a self-signed cert (as the real hub does); the client
 * accepts any chain/hostname and is held to the SPKI pin alone.
 */
class HubTlsTest {

    private lateinit var server: MockWebServer
    private lateinit var heldCertificate: HeldCertificate
    private lateinit var spkiPin: String
    private val base = OkHttpClient()

    @Before fun setUp() {
        heldCertificate = HeldCertificate.Builder()
            .commonName("LocalLexis Hub")
            .addSubjectAlternativeName("localhost")
            .build()
        val serverCerts = HandshakeCertificates.Builder()
            .heldCertificate(heldCertificate)
            .build()
        server = MockWebServer()
        server.useHttps(serverCerts.sslSocketFactory(), false)
        server.start()
        spkiPin = spkiB64(heldCertificate)
    }

    @After fun tearDown() {
        server.shutdown()
    }

    /** Mirrors speechtotext.api.tls.spki_fingerprint_b64: base64(sha256(SPKI DER)). */
    private fun spkiB64(cert: HeldCertificate): String {
        val spkiDer = cert.certificate.publicKey.encoded
        val digest = MessageDigest.getInstance("SHA-256").digest(spkiDer)
        return Base64.getEncoder().encodeToString(digest)
    }

    @Test fun correctPinConnects() {
        server.enqueue(MockResponse().setBody("ok"))
        val url = server.url("/").toString()
        val client = HubTls.pinnedClient(base, url, spkiPin)
        client.newCall(Request.Builder().url(url).build()).execute().use { resp ->
            assertEquals(200, resp.code)
            assertEquals("ok", resp.body?.string())
        }
    }

    @Test fun wrongPinIsRejected() {
        server.enqueue(MockResponse().setBody("ok"))
        val url = server.url("/").toString()
        val wrongPin = Base64.getEncoder().encodeToString(ByteArray(32) { 0 })
        val client = HubTls.pinnedClient(base, url, wrongPin)
        assertThrows(SSLException::class.java) {
            client.newCall(Request.Builder().url(url).build()).execute()
        }
    }

    @Test fun httpUrlReturnsBaseUnchanged() {
        assertSame(base, HubTls.pinnedClient(base, "http://192.168.1.5:8000", spkiPin))
    }

    @Test fun nullPinOnHttpsReturnsBaseUnchanged() {
        assertSame(base, HubTls.pinnedClient(base, "https://192.168.1.5:8443", null))
    }

    @Test fun blankPinReturnsBaseUnchanged() {
        assertSame(base, HubTls.pinnedClient(base, "https://192.168.1.5:8443", "   "))
    }
}
