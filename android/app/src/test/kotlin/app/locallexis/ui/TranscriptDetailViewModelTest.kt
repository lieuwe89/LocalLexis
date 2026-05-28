package app.locallexis.ui

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import app.locallexis.data.db.LocalLexisDatabase
import app.locallexis.data.db.SegmentEntity
import app.locallexis.data.db.SpeakerEntity
import app.locallexis.data.db.TranscriptEntity
import app.locallexis.ui.library.TranscriptDetailUiState
import app.locallexis.ui.library.TranscriptDetailViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class TranscriptDetailViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var db: LocalLexisDatabase

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, LocalLexisDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        db.close()
        Dispatchers.resetMain()
    }

    @Test
    fun readyHasSegmentsAndSpeakerNames() = runTest(testDispatcher) {
        db.transcriptDao().upsert(transcript("t1"))
        db.segmentDao().upsertAll(
            listOf(
                SegmentEntity("t1", 0, 0.0, 5.0, "hello", "SPEAKER_00"),
                SegmentEntity("t1", 1, 5.0, 10.0, "hi", "SPEAKER_01"),
            )
        )
        db.speakerDao().upsertAll(
            listOf(
                SpeakerEntity("t1", "SPEAKER_00", "Alice"),
                SpeakerEntity("t1", "SPEAKER_01", "Bob"),
            )
        )

        val vm = TranscriptDetailViewModel(
            db = db,
            transcriptId = "t1",
            scope = TestScope(testDispatcher),
        )
        advanceUntilIdle()

        val state = vm.uiState.first { it is TranscriptDetailUiState.Ready }
        assertTrue(state is TranscriptDetailUiState.Ready)
        val ready = state as TranscriptDetailUiState.Ready
        assertEquals("t1", ready.transcript.id)
        assertEquals(2, ready.segments.size)
        assertEquals("Alice", ready.segments[0].speakerName)
        assertEquals("Bob", ready.segments[1].speakerName)
    }

    @Test
    fun unknownIdIsNotFound() = runTest(testDispatcher) {
        val vm = TranscriptDetailViewModel(
            db = db,
            transcriptId = "missing",
            scope = TestScope(testDispatcher),
        )
        advanceUntilIdle()

        val state = vm.uiState.first { it !is TranscriptDetailUiState.Loading }
        assertEquals(TranscriptDetailUiState.NotFound, state)
    }

    @Test
    fun missingSpeakerMapKeepsSpeakerIdInPlace() = runTest(testDispatcher) {
        db.transcriptDao().upsert(transcript("t1"))
        db.segmentDao().upsertAll(
            listOf(SegmentEntity("t1", 0, 0.0, 5.0, "hello", "SPEAKER_99"))
        )
        // No speaker entity for SPEAKER_99.

        val vm = TranscriptDetailViewModel(
            db = db,
            transcriptId = "t1",
            scope = TestScope(testDispatcher),
        )
        advanceUntilIdle()

        val state = vm.uiState.first { it is TranscriptDetailUiState.Ready }
        val ready = state as TranscriptDetailUiState.Ready
        assertEquals("SPEAKER_99", ready.segments[0].speakerName)
    }

    private fun transcript(id: String) = TranscriptEntity(
        id = id,
        workspaceId = "ws_a",
        audioPath = "/audio/$id.mp3",
        audioBasename = "$id.mp3",
        durationSeconds = 60.0,
        language = "en",
        createdAt = "2026-05-20T10:00:00Z",
        jsonMtime = 1716200000.0,
        modelsAsr = null,
        modelsDiarizer = null,
        rawJson = "{}",
    )
}
