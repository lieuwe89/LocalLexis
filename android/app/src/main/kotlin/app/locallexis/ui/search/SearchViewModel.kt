package app.locallexis.ui.search

import app.locallexis.data.db.SearchDao
import app.locallexis.data.db.SearchHit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Drives local full-text search over synced segments. The query is run on
 * every change (search is a cheap local FTS lookup); a blank or operator-only
 * query short-circuits to no results without touching the DAO. FTS syntax
 * errors are swallowed to an empty result rather than crashing the screen.
 */
class SearchViewModel(
    private val searchDao: SearchDao,
    private val scope: CoroutineScope,
) {
    private val _query = MutableStateFlow("")
    val query: StateFlow<String> = _query.asStateFlow()

    private val _results = MutableStateFlow<List<SearchHit>>(emptyList())
    val results: StateFlow<List<SearchHit>> = _results.asStateFlow()

    fun onQueryChange(text: String) {
        _query.value = text
        val match = buildFtsMatchQuery(text)
        if (match == null) {
            _results.value = emptyList()
            return
        }
        scope.launch {
            _results.value = runCatching { searchDao.searchSegments(match) }
                .getOrDefault(emptyList())
        }
    }

    fun clear() {
        _query.value = ""
        _results.value = emptyList()
    }
}
