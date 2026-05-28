package app.locallexis.data.sync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import app.locallexis.data.db.LocalLexisDatabase
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
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
class SyncIngestTest {

    private lateinit var db: LocalLexisDatabase
    private lateinit var ingest: SyncIngest

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, LocalLexisDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        ingest = SyncIngest(db)
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun ingestSnapshotWritesTranscriptSegmentsAndSpeakers() = runTest {
        val response = SyncResponse(
            workspaceId = "ws_a",
            cursor = 1716200000.5,
            transcripts = listOf(
                WireTranscript(
                    id = "t1",
                    workspaceId = "ws_a",
                    audioPath = "/audio/m.mp3",
                    durationSeconds = 60.0,
                    language = "nl",
                    createdAt = "2026-05-20T10:00:00Z",
                    models = WireModels(asr = "whisper", diarizer = "pyannote"),
                    speakers = mapOf("SPEAKER_00" to "Alice", "SPEAKER_01" to "Bob"),
                    segments = listOf(
                        WireSegment(0.0, 5.0, "hello", "SPEAKER_00"),
                        WireSegment(5.0, 10.0, "hi there", "SPEAKER_01"),
                    ),
                    rawJson = """{"id":"t1"}""",
                ),
            ),
        )

        ingest.applySnapshot(response)

        val stored = db.transcriptDao().getById("t1")
        assertNotNull(stored)
        assertEquals("ws_a", stored!!.workspaceId)
        assertEquals("nl", stored.language)
        assertEquals("whisper", stored.modelsAsr)
        assertEquals(1716200000.5, stored.jsonMtime, 1e-6)

        val segments = db.segmentDao().forTranscript("t1")
        assertEquals(2, segments.size)
        assertEquals("hello", segments[0].text)
        assertEquals("SPEAKER_00", segments[0].speakerId)

        val speakers = db.speakerDao().forTranscript("t1").first()
        assertEquals(setOf("Alice", "Bob"), speakers.map { it.name }.toSet())

        val cursor = db.syncStateDao().getCursor("ws_a")
        assertEquals(1716200000.5, cursor!!, 1e-6)
    }

    @Test
    fun reIngestOverwrites() = runTest {
        ingest.applySnapshot(
            SyncResponse(
                workspaceId = "ws_a",
                cursor = 100.0,
                transcripts = listOf(
                    makeWire("t1", segments = listOf(WireSegment(0.0, 5.0, "first take", "SPEAKER_00"))),
                ),
            )
        )
        ingest.applySnapshot(
            SyncResponse(
                workspaceId = "ws_a",
                cursor = 200.0,
                transcripts = listOf(
                    makeWire("t1", segments = listOf(WireSegment(0.0, 5.0, "second take", "SPEAKER_00"))),
                ),
            )
        )

        val segments = db.segmentDao().forTranscript("t1")
        assertEquals(1, segments.size)
        assertEquals("second take", segments[0].text)
        assertEquals(200.0, db.syncStateDao().getCursor("ws_a")!!, 1e-6)
    }

    @Test
    fun emptyTranscriptListStillAdvancesCursor() = runTest {
        ingest.applySnapshot(
            SyncResponse(workspaceId = "ws_a", cursor = 500.0, transcripts = emptyList())
        )

        assertEquals(500.0, db.syncStateDao().getCursor("ws_a")!!, 1e-6)
    }

    private fun makeWire(id: String, segments: List<WireSegment>) = WireTranscript(
        id = id,
        workspaceId = "ws_a",
        audioPath = "/a/$id.mp3",
        durationSeconds = 30.0,
        language = "en",
        createdAt = "2026-05-20T10:00:00Z",
        models = WireModels(asr = null, diarizer = null),
        speakers = mapOf("SPEAKER_00" to "Alice"),
        segments = segments,
        rawJson = """{"id":"$id"}""",
    )
}
