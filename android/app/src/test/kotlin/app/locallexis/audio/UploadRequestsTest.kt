package app.locallexis.audio

import org.junit.Assert.assertEquals
import org.junit.Test

class UploadRequestsTest {

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
