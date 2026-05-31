package app.locallexis.data.pairing

import app.locallexis.data.crypto.InMemorySecretStorage
import app.locallexis.data.crypto.LazysodiumCryptoBox
import com.goterl.lazysodium.LazySodiumJava
import com.goterl.lazysodium.SodiumJava
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertThrows
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.Base64

class SignedRequestInterceptorTest {

    private lateinit var server: MockWebServer
    private lateinit var sodium: LazySodiumJava
    private lateinit var crypto: LazysodiumCryptoBox
    private lateinit var identityStore: InMemoryDeviceIdentityStore
    private lateinit var http: OkHttpClient

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        sodium = LazySodiumJava(SodiumJava())
        crypto = LazysodiumCryptoBox(InMemorySecretStorage(), sodium)
        identityStore = InMemoryDeviceIdentityStore().apply { putDeviceId("dev_abc") }
        http = OkHttpClient.Builder()
            .addInterceptor(SignedRequestInterceptor(crypto, identityStore))
            .build()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun addsDeviceIdAndSignatureHeaders() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val req = Request.Builder()
            .url(server.url("/sync/snapshot"))
            .get()
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        assertEquals("dev_abc", recorded.getHeader("X-Device-Id"))
        val sigB64 = recorded.getHeader("X-Signature-B64")
        assertNotNull("signature header present", sigB64)

        val timestamp = recorded.getHeader("X-Timestamp")
        val nonce = recorded.getHeader("X-Nonce")
        assertNotNull("timestamp header present", timestamp)
        assertNotNull("nonce header present", nonce)
        val nl = byteArrayOf(0x0A)
        val emptyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(0))
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "GET".toByteArray() + nl +
            "/sync/snapshot".toByteArray() + nl +
            "$timestamp".toByteArray() + nl +
            "$nonce".toByteArray() + nl +
            emptyDigest
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue("v2 signature verifies", ok)
    }

    @Test
    fun signsQueryTimestampAndNonceForReplayProtectedHubAuth() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val req = Request.Builder()
            .url(server.url("/sync/snapshot?limit=2&offset=4"))
            .get()
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        val timestamp = recorded.getHeader("X-Timestamp")
        val nonce = recorded.getHeader("X-Nonce")
        val sigB64 = recorded.getHeader("X-Signature-B64")
        assertNotNull("timestamp header present", timestamp)
        assertNotNull("nonce header present", nonce)
        assertNotNull("signature header present", sigB64)
        assertTrue("nonce is 128-bit hex", nonce!!.matches(Regex("[0-9a-f]{32}")))

        val nl = byteArrayOf(0x0A)
        val emptyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(0))
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "GET".toByteArray() + nl +
            "/sync/snapshot?limit=2&offset=4".toByteArray() + nl +
            "$timestamp".toByteArray() + nl +
            "$nonce".toByteArray() + nl +
            emptyDigest
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue("v2 signature verifies against replay-protected hub bytes", ok)
    }

    @Test
    fun signsPatchBody() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val body = """{"key":"speakers.SPEAKER_00","value":"Alice"}""".toByteArray()
        val req = Request.Builder()
            .url(server.url("/transcripts/abc/relabel"))
            .patch(body.toRequestBody())
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        val sigB64 = recorded.getHeader("X-Signature-B64")!!
        val timestamp = recorded.getHeader("X-Timestamp")
        val nonce = recorded.getHeader("X-Nonce")
        assertNotNull("timestamp header present", timestamp)
        assertNotNull("nonce header present", nonce)
        val nl = byteArrayOf(0x0A)
        val bodyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(body)
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "PATCH".toByteArray() + nl +
            "/transcripts/abc/relabel".toByteArray() + nl +
            "$timestamp".toByteArray() + nl +
            "$nonce".toByteArray() + nl +
            bodyDigest
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue(ok)
    }

    @Test
    fun rejectsOversizedSignedBody() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val body = ByteArray(1_048_577) { 0 }.toRequestBody()
        val req = Request.Builder()
            .url(server.url("/transcripts/abc/relabel"))
            .patch(body)
            .build()

        assertThrows(java.io.IOException::class.java) {
            http.newCall(req).execute().close()
        }
    }

    @Test
    fun signsLargeBodyWhenTaggedForUpload() {
        server.enqueue(MockResponse().setResponseCode(202).setBody("{}"))

        // 2 MiB exceeds the 1 MiB small-request cap; the upload tag lifts it.
        val body = ByteArray(2 * 1024 * 1024) { 7 }.toRequestBody()
        val req = Request.Builder()
            .url(server.url("/jobs/upload?filename=rec.m4a"))
            .post(body)
            .tag(SignLargeBody::class.java, SignLargeBody)
            .build()

        http.newCall(req).execute().close()

        val recorded = server.takeRequest()
        assertEquals("dev_abc", recorded.getHeader("X-Device-Id"))
        assertNotNull("large tagged body is signed", recorded.getHeader("X-Signature-B64"))
        assertEquals(2 * 1024 * 1024, recorded.bodySize.toInt())
    }

    @Test
    fun unregisteredDeviceSkipsSigning() {
        val unidentified = InMemoryDeviceIdentityStore()
        val unsignedHttp = OkHttpClient.Builder()
            .addInterceptor(SignedRequestInterceptor(crypto, unidentified))
            .build()

        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

        val req = Request.Builder().url(server.url("/x")).get().build()
        unsignedHttp.newCall(req).execute().close()

        val recorded = server.takeRequest()
        assertEquals(null, recorded.getHeader("X-Device-Id"))
        assertEquals(null, recorded.getHeader("X-Signature-B64"))
    }
}
