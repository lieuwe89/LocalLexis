package app.locallexis.data.sync

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

/**
 * Wire client for the hub's `/sync/snapshot` and `/sync/since/{cursor}`
 * endpoints. The [httpClient] must already have the
 * [app.locallexis.data.pairing.SignedRequestInterceptor] attached — this
 * layer assumes signed-request auth is taken care of one level down.
 */
class SyncClient(
    private val httpClient: OkHttpClient,
    private val baseUrl: String,
    private val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    },
) {

    suspend fun snapshot(): SyncResponse = getSync("$baseUrl/sync/snapshot")

    suspend fun since(cursor: Double): SyncResponse {
        // BigDecimal.valueOf uses Double.toString semantics for the
        // unscaled value, then toPlainString avoids 1.0E9-style scientific
        // notation that would break path-parameter parsing on some setups.
        val plain = java.math.BigDecimal.valueOf(cursor).toPlainString()
        return getSync("$baseUrl/sync/since/$plain")
    }

    private suspend fun getSync(url: String): SyncResponse = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url).get().build()
        val response = try {
            httpClient.newCall(request).execute()
        } catch (e: IOException) {
            throw SyncException(0, "network error: ${e.message}")
        }
        response.use {
            if (!it.isSuccessful) {
                throw SyncException(it.code, "hub returned HTTP ${it.code}")
            }
            val body = it.body?.string() ?: throw SyncException(it.code, "empty response body")
            try {
                // Parse the envelope and per-transcript docs separately
                // so we can capture each transcript's raw JSON without
                // round-tripping through @Serializable.
                val envelope = json.parseToJsonElement(body).jsonObject
                val workspaceId = envelope["workspace_id"]?.toString()?.trim('"')
                    ?: throw SyncException(it.code, "missing workspace_id")
                val cursorValue = envelope["cursor"]?.toString()?.toDoubleOrNull()
                    ?: throw SyncException(it.code, "missing or non-numeric cursor")
                val transcriptsJson: JsonArray = envelope["transcripts"]?.jsonArray
                    ?: JsonArray(emptyList())
                val transcripts = transcriptsJson.map { docElement ->
                    parseTranscript(docElement, it.code)
                }
                SyncResponse(
                    workspaceId = workspaceId,
                    cursor = cursorValue,
                    transcripts = transcripts,
                )
            } catch (e: SyncException) {
                throw e
            } catch (e: Throwable) {
                throw SyncException(it.code, "malformed sync response: ${e.message}")
            }
        }
    }

    private fun parseTranscript(element: JsonElement, httpCode: Int): WireTranscript {
        val obj: JsonObject = element.jsonObject
        if (obj["id"] == null) {
            throw SyncException(
                httpCode,
                "transcript doc missing 'id' field — hub /sync/snapshot must surface json_path.stem",
            )
        }
        val parsed = json.decodeFromJsonElement(WireTranscript.serializer(), obj)
        return parsed.copy(rawJson = obj.toString())
    }
}

class SyncException(
    val httpStatus: Int,
    message: String,
) : RuntimeException(message)
