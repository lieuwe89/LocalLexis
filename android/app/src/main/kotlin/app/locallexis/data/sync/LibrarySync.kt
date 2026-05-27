package app.locallexis.data.sync

/**
 * Orchestrator coupling [SyncClient] (network) and [SyncIngest] (Room).
 * Callers use [bootstrap] once on first launch and [incremental] for
 * subsequent polls.
 */
class LibrarySync(
    private val client: SyncClient,
    private val ingest: SyncIngest,
) {

    /** Full snapshot — used on first paired sync and on local DB reset. */
    suspend fun bootstrap(): SyncResponse {
        val response = client.snapshot()
        ingest.applySnapshot(response)
        return response
    }

    /**
     * Delta sync from the persisted cursor for [workspaceId]. If no
     * cursor has been recorded yet, falls through to [bootstrap].
     */
    suspend fun incremental(workspaceId: String): SyncResponse {
        val storedCursor = ingest.cursorFor(workspaceId) ?: return bootstrap()
        val response = client.since(storedCursor)
        ingest.applySnapshot(response)
        return response
    }
}
