package app.locallexis.ui

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import app.locallexis.data.db.LocalLexisDatabase
import app.locallexis.data.db.TranscriptEntity
import app.locallexis.data.sync.LibrarySync
import app.locallexis.data.sync.SyncException
import app.locallexis.data.sync.SyncResponse
import app.locallexis.ui.library.LibraryUiState
import app.locallexis.ui.library.LibraryViewModel
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
class LibraryViewModelTest {

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
    fun emitsReadyWithSummariesFromRoom() = runTest(testDispatcher) {
        db.transcriptDao().upsert(transcript("a", "alpha.mp3", "2026-05-20T10:00:00Z"))
        db.transcriptDao().upsert(transcript("b", "beta.mp3", "2026-05-22T10:00:00Z"))

        val sync = FakeLibrarySync()
        val vm = LibraryViewModel(
            transcriptDao = db.transcriptDao(),
            sync = sync,
            workspaceId = "ws_a",
            scope = TestScope(testDispatcher),
        )

        advanceUntilIdle()
        val state = vm.uiState.first { it is LibraryUiState.Ready }
        assertTrue(state is LibraryUiState.Ready)
        val summaries = (state as LibraryUiState.Ready).transcripts
        // Newest first per createdAt DESC ordering.
        assertEquals(listOf("b", "a"), summaries.map { it.id })
        assertEquals("beta.mp3", summaries[0].audioBasename)
    }

    @Test
    fun refreshTriggersIncrementalSync() = runTest(testDispatcher) {
        val sync = FakeLibrarySync()
        val vm = LibraryViewModel(
            transcriptDao = db.transcriptDao(),
            sync = sync,
            workspaceId = "ws_a",
            scope = TestScope(testDispatcher),
        )

        vm.refresh()
        advanceUntilIdle()

        assertEquals(1, sync.incrementalCalls)
        assertEquals("ws_a", sync.lastWorkspaceId)
    }

    @Test
    fun syncFailureSurfacesAsErrorButLeavesPriorRowsVisible() = runTest(testDispatcher) {
        db.transcriptDao().upsert(transcript("a", "alpha.mp3", "2026-05-20T10:00:00Z"))

        val sync = FakeLibrarySync().apply { failNext = SyncException(401, "auth fail") }
        val vm = LibraryViewModel(
            transcriptDao = db.transcriptDao(),
            sync = sync,
            workspaceId = "ws_a",
            scope = TestScope(testDispatcher),
        )

        val readyState = vm.uiState.first { it is LibraryUiState.Ready }
        assertTrue("local rows visible before refresh", readyState is LibraryUiState.Ready)

        vm.refresh()
        advanceUntilIdle()

        // Local rows remain visible after a failed sync.
        val afterRefresh = vm.uiState.value
        assertTrue("local rows still visible", afterRefresh is LibraryUiState.Ready)
        assertEquals("auth fail", vm.lastError.value)
    }

    private fun transcript(id: String, basename: String, createdAt: String) = TranscriptEntity(
        id = id,
        workspaceId = "ws_a",
        audioPath = "/audio/$basename",
        audioBasename = basename,
        durationSeconds = 60.0,
        language = "en",
        createdAt = createdAt,
        jsonMtime = 1716200000.0,
        modelsAsr = null,
        modelsDiarizer = null,
        rawJson = "{}",
    )
}

class FakeLibrarySync : LibrarySync {
    var incrementalCalls: Int = 0
    var bootstrapCalls: Int = 0
    var lastWorkspaceId: String? = null
    var failNext: Throwable? = null

    override suspend fun bootstrap(): SyncResponse {
        bootstrapCalls++
        failNext?.let { failNext = null; throw it }
        return SyncResponse(workspaceId = "ws_a", cursor = 0.0, transcripts = emptyList())
    }

    override suspend fun incremental(workspaceId: String): SyncResponse {
        incrementalCalls++
        lastWorkspaceId = workspaceId
        failNext?.let { failNext = null; throw it }
        return SyncResponse(workspaceId = workspaceId, cursor = 0.0, transcripts = emptyList())
    }
}
