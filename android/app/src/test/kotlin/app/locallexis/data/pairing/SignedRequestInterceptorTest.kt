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

        // Reconstruct message Hub-side and verify with device pubkey.
        val message = ("GET\n/sync/snapshot\n").toByteArray()
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue("signature verifies", ok)
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
        val message = ("PATCH\n/transcripts/abc/relabel\n").toByteArray() + body
        val sig = Base64.getDecoder().decode(sigB64)
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, crypto.devicePublicKey())
        assertTrue(ok)
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
