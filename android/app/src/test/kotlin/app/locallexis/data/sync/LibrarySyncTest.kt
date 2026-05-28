package app.locallexis.data.sync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import app.locallexis.data.crypto.InMemorySecretStorage
import app.locallexis.data.crypto.LazysodiumCryptoBox
import app.locallexis.data.db.LocalLexisDatabase
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
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class LibrarySyncTest {

    private lateinit var server: MockWebServer
    private lateinit var db: LocalLexisDatabase
    private lateinit var libsync: LibrarySync

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, LocalLexisDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        val sodium = LazySodiumJava(SodiumJava())
        val crypto = LazysodiumCryptoBox(InMemorySecretStorage(), sodium)
        val identity = InMemoryDeviceIdentityStore().apply { putDeviceId("dev_1") }
        val http = OkHttpClient.Builder()
            .addInterceptor(SignedRequestInterceptor(crypto, identity))
            .build()
        val client = SyncClient(http, server.url("/").toString().trimEnd('/'))
        libsync = DefaultLibrarySync(client, SyncIngest(db))
    }

    @After
    fun tearDown() {
        server.shutdown()
        db.close()
    }

    @Test
    fun bootstrapSyncsSnapshotIntoRoom() = runTest {
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
                      "audio_path": "/a/m.mp3",
                      "duration_seconds": 60.0,
                      "language": "nl",
                      "created_at": "2026-05-20T10:00:00Z",
                      "models": {"asr": "whisper", "diarizer": null},
                      "speakers": {"SPEAKER_00": "Alice"},
                      "segments": [
                        {"start": 0.0, "end": 5.0, "text": "hi", "speaker_id": "SPEAKER_00"}
                      ]
                    },
                    {
                      "id": "t2",
                      "_workspace_id": "ws_a",
                      "audio_path": "/a/n.mp3",
                      "duration_seconds": 30.0,
                      "language": "en",
                      "created_at": "2026-05-21T10:00:00Z",
                      "models": {"asr": "whisper", "diarizer": "pyannote"},
                      "speakers": {},
                      "segments": []
                    }
                  ]
                }
                """.trimIndent()
            )
        )

        libsync.bootstrap()

        assertNotNull(db.transcriptDao().getById("t1"))
        assertNotNull(db.transcriptDao().getById("t2"))
        assertEquals(1716200000.5, db.syncStateDao().getCursor("ws_a")!!, 1e-6)
    }

    @Test
    fun incrementalUsesPersistedCursor() = runTest {
        // Pre-existing cursor.
        db.syncStateDao().upsert(
            app.locallexis.data.db.SyncStateEntity("ws_a", 1716200000.0, null)
        )

        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {"workspace_id":"ws_a","cursor":1716300000.0,"transcripts":[]}
                """.trimIndent()
            )
        )

        libsync.incremental("ws_a")

        val req = server.takeRequest()
        assertEquals("GET", req.method)
        assertEquals("/sync/since/1716200000", req.path)
        assertEquals(1716300000.0, db.syncStateDao().getCursor("ws_a")!!, 1e-6)
    }
}
