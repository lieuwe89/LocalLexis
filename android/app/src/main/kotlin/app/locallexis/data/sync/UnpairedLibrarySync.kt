package app.locallexis.data.sync

/**
 * [LibrarySync] used when no hub is paired. Every operation fails with
 * [NotPairedException]; LibraryViewModel.refresh catches it into
 * `lastError` without disturbing the (empty) local list.
 */
object UnpairedLibrarySync : LibrarySync {
    override suspend fun bootstrap(): SyncResponse = throw NotPairedException()
    override suspend fun incremental(workspaceId: String): SyncResponse = throw NotPairedException()
}

class NotPairedException : RuntimeException("no hub paired — pair a hub to sync")
