package app.locallexis.data.pairing

import app.locallexis.data.crypto.InMemorySecretStorage
import app.locallexis.data.crypto.InMemoryWorkspaceKeyStore
import app.locallexis.data.crypto.LazysodiumCryptoBox
import com.goterl.lazysodium.LazySodiumJava
import com.goterl.lazysodium.SodiumJava
import com.goterl.lazysodium.interfaces.Box
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.util.Base64

class PairingClientTest {

    private lateinit var server: MockWebServer
    private lateinit var sodium: LazySodiumJava
    private lateinit var crypto: LazysodiumCryptoBox
    private lateinit var workspaceStore: InMemoryWorkspaceKeyStore
    private lateinit var identityStore: InMemoryDeviceIdentityStore
    private lateinit var client: PairingClient

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        sodium = LazySodiumJava(SodiumJava())
        crypto = LazysodiumCryptoBox(InMemorySecretStorage(), sodium)
        workspaceStore = InMemoryWorkspaceKeyStore()
        identityStore = InMemoryDeviceIdentityStore()
        client = PairingClient(
            cryptoBox = crypto,
            workspaceKeyStore = workspaceStore,
            deviceIdentityStore = identityStore,
            httpClient = OkHttpClient(),
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun successfulPairingStoresKeyAndIdentity() = runTest {
        val workspaceKey = ByteArray(32) { it.toByte() }
        val devicePub = crypto.devicePublicKey()
        val sealedB64 = sealForDevice(devicePub, workspaceKey)

        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "device_id": "dev_assigned_123",
                  "workspace_id": "ws_a",
                  "workspace_key_sealed_b64": "$sealedB64",
                  "lamport_observed": 42
                }
                """.trimIndent()
            )
        )

        val payload = PairingPayloadV1(
            hubUrl = server.url("/").toString().trimEnd('/'),
            workspaceId = "ws_a",
            token = "tok_xyz",
            tlsSpkiB64 = null,
        )

        val result = client.exchange(payload, "Pixel 8")

        assertEquals("dev_assigned_123", result.deviceId)
        assertEquals("ws_a", result.workspaceId)
        assertEquals(42L, result.lamportObserved)

        assertArrayEquals("workspace key stored", workspaceKey, workspaceStore.get())
        assertEquals("dev_assigned_123", identityStore.getDeviceId())

        val req: RecordedRequest = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/pair", req.path)
        val sentBody = req.body.readUtf8()
        assertTrue("body has token", sentBody.contains("tok_xyz"))
        assertTrue("body has pubkey b64", sentBody.contains("device_pubkey_b64"))
        assertTrue("body has device_name", sentBody.contains("Pixel 8"))
    }

    @Test
    fun invalidTokenReturns401Wrapped() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(401).setBody(
                """{"detail":"invalid pairing token"}"""
            )
        )

        val payload = PairingPayloadV1(
            hubUrl = server.url("/").toString().trimEnd('/'),
            workspaceId = "ws_a",
            token = "bad",
            tlsSpkiB64 = null,
        )

        try {
            client.exchange(payload, "Phone")
            fail("expected PairingFailedException")
        } catch (e: PairingFailedException) {
            assertEquals(401, e.httpStatus)
        }

        assertNull("workspace key not stored on failure", workspaceStore.get())
        assertNull("device id not stored on failure", identityStore.getDeviceId())
    }

    @Test
    fun corruptSealedBoxFailsWithoutStoringKey() = runTest {
        // Sealed b64 that decodes but won't open with this device's secret.
        val workspaceKey = ByteArray(32) { it.toByte() }
        val devicePub = crypto.devicePublicKey()
        var sealed = Base64.getDecoder().decode(sealForDevice(devicePub, workspaceKey))
        sealed[sealed.size - 1] = (sealed[sealed.size - 1].toInt() xor 0xFF).toByte()
        val tamperedB64 = Base64.getEncoder().encodeToString(sealed)

        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "device_id": "dev_x",
                  "workspace_id": "ws_a",
                  "workspace_key_sealed_b64": "$tamperedB64",
                  "lamport_observed": 0
                }
                """.trimIndent()
            )
        )

        val payload = PairingPayloadV1(
            hubUrl = server.url("/").toString().trimEnd('/'),
            workspaceId = "ws_a",
            token = "tok",
            tlsSpkiB64 = null,
        )

        try {
            client.exchange(payload, "Phone")
            fail("expected PairingFailedException")
        } catch (e: PairingFailedException) {
            assertTrue("error indicates sealedbox", e.message!!.contains("sealedbox", ignoreCase = true))
        }

        assertNull(workspaceStore.get())
        assertNull(identityStore.getDeviceId())
    }

    @Test
    fun parsePayloadFromQrAndExchange() = runTest {
        val workspaceKey = ByteArray(32) { 7 }
        val devicePub = crypto.devicePublicKey()
        val sealedB64 = sealForDevice(devicePub, workspaceKey)

        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "device_id": "d1",
                  "workspace_id": "ws_a",
                  "workspace_key_sealed_b64": "$sealedB64",
                  "lamport_observed": 0
                }
                """.trimIndent()
            )
        )

        val qrJson = """
            {
              "hub_url": "${server.url("/").toString().trimEnd('/')}",
              "workspace_id": "ws_a",
              "token": "fresh"
            }
        """.trimIndent()
        val payload = PairingPayloadV1.parse(qrJson)
        val result = client.exchange(payload, "Phone")
        assertEquals("d1", result.deviceId)
        assertNotNull(workspaceStore.get())
    }

    private fun sealForDevice(devicePub: ByteArray, plaintext: ByteArray): String {
        val curvePub = ByteArray(Box.PUBLICKEYBYTES)
        sodium.convertPublicKeyEd25519ToCurve25519(curvePub, devicePub)
        val sealed = ByteArray(plaintext.size + Box.SEALBYTES)
        sodium.cryptoBoxSeal(sealed, plaintext, plaintext.size.toLong(), curvePub)
        return Base64.getEncoder().encodeToString(sealed)
    }
}

class InMemoryDeviceIdentityStore : DeviceIdentityStore {
    @Volatile
    private var deviceId: String? = null
    override fun getDeviceId(): String? = deviceId
    override fun putDeviceId(id: String) {
        deviceId = id
    }
    override fun clear() {
        deviceId = null
    }
}
