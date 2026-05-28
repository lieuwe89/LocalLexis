package app.locallexis.data.sync

/**
 * Orchestrator coupling the network client and the Room ingest layer.
 * Modelled as an interface so view-model tests can swap in fakes
 * without having to construct a real OkHttp client or in-memory Room
 * DB just to drive UI state transitions.
 */
interface LibrarySync {

    /** Full snapshot — used on first paired sync and on local DB reset. */
    suspend fun bootstrap(): SyncResponse

    /**
     * Delta sync from the persisted cursor for [workspaceId]. If no
     * cursor has been recorded yet, falls through to [bootstrap].
     */
    suspend fun incremental(workspaceId: String): SyncResponse
}

class DefaultLibrarySync(
    private val client: SyncClient,
    private val ingest: SyncIngest,
) : LibrarySync {

    override suspend fun bootstrap(): SyncResponse {
        val response = client.snapshot()
        ingest.applySnapshot(response)
        return response
    }

    override suspend fun incremental(workspaceId: String): SyncResponse {
        val storedCursor = ingest.cursorFor(workspaceId) ?: return bootstrap()
        val response = client.since(storedCursor)
        ingest.applySnapshot(response)
        return response
    }
}
