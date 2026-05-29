package app.locallexis.ui.update

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateCheckerTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test fun parsesSemverVariants() {
        assertEquals(Triple(0, 9, 0), parseSemver("v0.9.0"))
        assertEquals(Triple(1, 2, 0), parseSemver("1.2"))
        assertEquals(Triple(2, 0, 0), parseSemver("2"))
        assertEquals(Triple(1, 4, 3), parseSemver("v1.4.3-rc1"))
        assertNull(parseSemver("nightly"))
    }

    @Test fun comparesSemver() {
        assertTrue(compareSemver("v0.9.0", "0.8.1") > 0)
        assertTrue(compareSemver("0.8.0", "v0.9.0") < 0)
        assertEquals(0, compareSemver("v1.0.0", "1.0.0"))
        assertEquals(0, compareSemver("garbage", "1.0.0"))
    }

    @Test fun parsesReleaseWithApkAsset() {
        val body = """
            {
              "tag_name": "v0.9.0",
              "html_url": "https://github.com/lieuwe89/LocalLexis/releases/tag/v0.9.0",
              "draft": false,
              "prerelease": false,
              "assets": [
                {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
                {"name": "app-release.apk", "browser_download_url": "https://x/app-release.apk"}
              ]
            }
        """.trimIndent()
        val info = parseLatestRelease(json, body)
        assertEquals("v0.9.0", info?.version)
        assertEquals("https://x/app-release.apk", info?.apkUrl)
        assertEquals(
            "https://github.com/lieuwe89/LocalLexis/releases/tag/v0.9.0",
            info?.releaseUrl,
        )
    }

    @Test fun ignoresPrereleaseAndAssetlessReleases() {
        val prerelease = """{"tag_name":"v1.0.0","prerelease":true,"assets":[{"name":"a.apk","browser_download_url":"u"}]}"""
        assertNull(parseLatestRelease(json, prerelease))

        val noApk = """{"tag_name":"v1.0.0","assets":[{"name":"notes.txt","browser_download_url":"u"}]}"""
        assertNull(parseLatestRelease(json, noApk))
    }

    @Test fun returnsNullOnGarbageJson() {
        assertNull(parseLatestRelease(json, "not json"))
    }
}
