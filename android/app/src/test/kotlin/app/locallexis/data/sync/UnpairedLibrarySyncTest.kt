package app.locallexis.data.sync

import kotlinx.coroutines.test.runTest
import org.junit.Assert.fail
import org.junit.Test

class UnpairedLibrarySyncTest {
    @Test fun bootstrap_throws_not_paired() = runTest {
        try {
            UnpairedLibrarySync.bootstrap()
            fail("expected NotPairedException")
        } catch (_: NotPairedException) {
            // expected
        }
    }

    @Test fun incremental_throws_not_paired() = runTest {
        try {
            UnpairedLibrarySync.incremental("ws_1")
            fail("expected NotPairedException")
        } catch (_: NotPairedException) {
            // expected
        }
    }
}
