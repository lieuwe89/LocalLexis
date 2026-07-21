package app.locallexis.audio

import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class UploadRequestsTest {

    @get:Rule val tmp = TemporaryFolder()

    @Test fun pendingRecordingsPicksNonEmptyM4aOnly() {
        val dir = tmp.newFolder("recordings")
        File(dir, "a.m4a").writeText("audio")
        File(dir, "b.m4a").writeText("more")
        File(dir, "empty.m4a").createNewFile() // 0 bytes -> skipped
        File(dir, "notes.txt").writeText("x")   // wrong ext -> skipped
        val names = pendingRecordings(dir).map { it.name }
        assertEquals(listOf("a.m4a", "b.m4a"), names)
    }

    @Test fun pendingRecordingsEmptyWhenDirAbsent() {
        assertEquals(emptyList<File>(), pendingRecordings(File(tmp.root, "nope")))
    }


    @Test fun buildsUploadUrlWithFilenameQuery() {
        assertEquals(
            "https://192.168.1.50:8443/jobs/upload?filename=rec-20260529-201500.m4a",
            uploadUrl("https://192.168.1.50:8443", "rec-20260529-201500.m4a"),
        )
    }

    @Test fun trimsTrailingSlashOnBase() {
        assertEquals(
            "http://10.0.0.2:8000/jobs/upload?filename=a.m4a",
            uploadUrl("http://10.0.0.2:8000/", "a.m4a"),
        )
    }

    @Test fun safeFilenameCharsPassThrough() {
        assertEquals(
            "https://h:1/jobs/upload?filename=rec_2026.05-29.m4a",
            uploadUrl("https://h:1", "rec_2026.05-29.m4a"),
        )
    }
}
