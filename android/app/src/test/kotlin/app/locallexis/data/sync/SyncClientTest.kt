package app.locallexis.data.sync

import app.locallexis.data.crypto.InMemorySecretStorage
import app.locallexis.data.crypto.LazysodiumCryptoBox
import app.locallexis.data.pairing.InMemoryDeviceIdentityStore
import app.locallexis.data.pairing.SignedRequestInterceptor
import com.goterl.lazysodium.LazySodiumJava
import com.goterl.lazysodium.SodiumJava
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class SyncClientTest {

    private lateinit var server: MockWebServer
    private lateinit var crypto: LazysodiumCryptoBox
    private lateinit var identity: InMemoryDeviceIdentityStore
    private lateinit var http: OkHttpClient
    private lateinit var client: SyncClient

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val sodium = LazySodiumJava(SodiumJava())
        crypto = LazysodiumCryptoBox(InMemorySecretStorage(), sodium)
        identity = InMemoryDeviceIdentityStore().apply { putDeviceId("dev_1") }
        http = OkHttpClient.Builder()
            .addInterceptor(SignedRequestInterceptor(crypto, identity))
            .build()
        client = SyncClient(http, server.url("/").toString().trimEnd('/'))
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun snapshotReturnsParsedDocsAndSignsRequest() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "workspace_id": "ws_a",
                  "cursor": 1716200000.5,
                  "transcripts": [
                    {
                      "id": "t1",
                      "_workspace_id": "ws_a",
                      "audio_path": "/audio/a.mp3",
                      "duration_seconds": 60.0,
                      "language": "nl",
                      "created_at": "2026-05-20T10:00:00Z",
                      "models": {"asr": "whisper-large-v3", "diarizer": "pyannote-3.1"},
                      "speakers": {"SPEAKER_00": "Alice"},
                      "segments": [
                        {"start": 0.0, "end": 5.0, "text": "hello", "speaker_id": "SPEAKER_00"}
                      ]
                    }
                  ]
                }
                """.trimIndent()
            )
        )

        val result = client.snapshot()

        assertEquals("ws_a", result.workspaceId)
        assertEquals(1716200000.5, result.cursor, 1e-6)
        assertEquals(1, result.transcripts.size)
        assertEquals("t1", result.transcripts[0].id)
        assertEquals("nl", result.transcripts[0].language)
        assertEquals(1, result.transcripts[0].segments.size)
        assertEquals("hello", result.transcripts[0].segments[0].text)

        val req = server.takeRequest()
        assertEquals("GET", req.method)
        assertEquals("/sync/snapshot", req.path)
        assertEquals("dev_1", req.getHeader("X-Device-Id"))
        assertNotNull(req.getHeader("X-Signature-B64"))
    }

    @Test
    fun sinceUsesCursorPathAndIsSigned() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "workspace_id": "ws_a",
                  "cursor": 1716300000.0,
                  "transcripts": []
                }
                """.trimIndent()
            )
        )

        val result = client.since(1716200000.5)

        assertEquals(0, result.transcripts.size)
        assertEquals(1716300000.0, result.cursor, 1e-6)

        val req = server.takeRequest()
        assertEquals("GET", req.method)
        assertTrue("path encodes cursor", req.path!!.startsWith("/sync/since/1716200000.5"))
        assertNotNull(req.getHeader("X-Signature-B64"))
    }

    @Test
    fun authFailureSurfacesAsException() = runTest {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"unknown device"}"""))

        try {
            client.snapshot()
            org.junit.Assert.fail("expected SyncException")
        } catch (e: SyncException) {
            assertEquals(401, e.httpStatus)
        }
    }

    @Test
    fun docMissingIdIsRejected() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "workspace_id": "ws_a",
                  "cursor": 0.0,
                  "transcripts": [
                    {"_workspace_id": "ws_a", "audio_path": "/a.mp3", "segments": [], "speakers": {}}
                  ]
                }
                """.trimIndent()
            )
        )

        try {
            client.snapshot()
            org.junit.Assert.fail("expected SyncException for missing id")
        } catch (e: SyncException) {
            assertTrue(e.message!!.contains("id", ignoreCase = true))
        }
    }
}
