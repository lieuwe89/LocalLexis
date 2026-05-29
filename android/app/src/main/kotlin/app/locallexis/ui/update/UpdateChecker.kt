package app.locallexis.ui.update

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

data class UpdateInfo(
    val version: String,
    val apkUrl: String,
    val releaseUrl: String,
)

@Serializable
private data class GhAsset(
    @SerialName("name") val name: String = "",
    @SerialName("browser_download_url") val url: String = "",
)

@Serializable
private data class GhRelease(
    @SerialName("tag_name") val tagName: String = "",
    @SerialName("html_url") val htmlUrl: String = "",
    @SerialName("draft") val draft: Boolean = false,
    @SerialName("prerelease") val prerelease: Boolean = false,
    @SerialName("assets") val assets: List<GhAsset> = emptyList(),
)

/** Parse a (major, minor, patch) triple from a semver-ish tag; null if unparseable. */
internal fun parseSemver(raw: String): Triple<Int, Int, Int>? {
    val core = raw.trim().removePrefix("v").substringBefore('-').substringBefore('+')
    val parts = core.split('.')
    if (parts.isEmpty() || parts[0].isBlank()) return null
    val major = parts.getOrNull(0)?.toIntOrNull() ?: return null
    val minor = parts.getOrNull(1)?.toIntOrNull() ?: 0
    val patch = parts.getOrNull(2)?.toIntOrNull() ?: 0
    return Triple(major, minor, patch)
}

/** >0 if a newer than b, <0 if older, 0 if equal or either is unparseable. */
internal fun compareSemver(a: String, b: String): Int {
    val pa = parseSemver(a) ?: return 0
    val pb = parseSemver(b) ?: return 0
    return compareValuesBy(pa, pb, { it.first }, { it.second }, { it.third })
}

internal fun parseLatestRelease(json: Json, body: String): UpdateInfo? {
    val release = runCatching { json.decodeFromString(GhRelease.serializer(), body) }
        .getOrNull() ?: return null
    if (release.draft || release.prerelease || release.tagName.isBlank()) return null
    val apk = release.assets.firstOrNull { it.name.endsWith(".apk", ignoreCase = true) }
        ?: return null
    return UpdateInfo(version = release.tagName, apkUrl = apk.url, releaseUrl = release.htmlUrl)
}

/**
 * Polls the GitHub Releases API for a newer signed APK. Uses a plain client
 * (no device-signing interceptor — these are public, unauthenticated calls to
 * github.com, not the hub). Returns null on any network/parse failure or when
 * already up to date, so callers can treat "no update" as the quiet default.
 */
class UpdateChecker(
    private val httpClient: OkHttpClient = OkHttpClient(),
    private val owner: String = "lieuwe89",
    private val repo: String = "LocalLexis",
    private val json: Json = Json { ignoreUnknownKeys = true },
) {
    suspend fun check(currentVersion: String): UpdateInfo? = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("https://api.github.com/repos/$owner/$repo/releases/latest")
            .header("Accept", "application/vnd.github+json")
            .get()
            .build()
        val body = try {
            httpClient.newCall(request).execute().use {
                if (!it.isSuccessful) return@withContext null
                it.body?.string()
            }
        } catch (_: IOException) {
            return@withContext null
        } ?: return@withContext null

        val latest = parseLatestRelease(json, body) ?: return@withContext null
        if (compareSemver(latest.version, currentVersion) > 0) latest else null
    }
}
