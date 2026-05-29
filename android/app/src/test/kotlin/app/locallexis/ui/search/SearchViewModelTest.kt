package app.locallexis.ui.search

import app.locallexis.data.db.SearchDao
import app.locallexis.data.db.SearchHit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SearchViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    private class FakeSearchDao(private val hits: List<SearchHit>) : SearchDao {
        var lastQuery: String? = null
        var calls = 0
        override suspend fun searchSegments(query: String): List<SearchHit> {
            lastQuery = query
            calls++
            return hits
        }
    }

    private val sampleHits = listOf(
        SearchHit("t1", 0, "the quick brown fox", "the [quick] brown fox"),
    )

    @Before fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test fun queryRunsBuiltMatchAndPublishesHits() = runTest(testDispatcher) {
        val dao = FakeSearchDao(sampleHits)
        val vm = SearchViewModel(dao, TestScope(testDispatcher))

        vm.onQueryChange("quick brown")
        advanceUntilIdle()

        assertEquals("quick* brown*", dao.lastQuery)
        assertEquals(sampleHits, vm.results.value)
        assertEquals("quick brown", vm.query.value)
    }

    @Test fun blankQuerySkipsDaoAndClearsResults() = runTest(testDispatcher) {
        val dao = FakeSearchDao(sampleHits)
        val vm = SearchViewModel(dao, TestScope(testDispatcher))

        vm.onQueryChange("   ")
        advanceUntilIdle()

        assertNull(dao.lastQuery)
        assertEquals(0, dao.calls)
        assertTrue(vm.results.value.isEmpty())
    }

    @Test fun clearResetsQueryAndResults() = runTest(testDispatcher) {
        val dao = FakeSearchDao(sampleHits)
        val vm = SearchViewModel(dao, TestScope(testDispatcher))

        vm.onQueryChange("quick")
        advanceUntilIdle()
        assertTrue(vm.results.value.isNotEmpty())

        vm.clear()
        assertEquals("", vm.query.value)
        assertTrue(vm.results.value.isEmpty())
    }
}
