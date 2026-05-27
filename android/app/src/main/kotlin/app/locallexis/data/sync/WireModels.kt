package app.locallexis.data.sync

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * Wire shape of [speechtotext.api.routes_sync.SyncResponse]. Extra
 * underscored fields (_clocks, _history) are preserved as raw JSON on
 * the transcript level via [WireTranscript.rawJson] so the CRDT layer
 * can rehydrate the full state later without us shaping every field
 * up front.
 *
 * The `id` field is a hub-side addition needed by the mobile client to
 * key the local Room rows. Hub currently produces transcript files
 * whose stem is the id (see speechtotext.api.library_db.upsert_path);
 * the /sync/snapshot endpoint must surface that on the wire.
 */
@Serializable
data class SyncResponse(
    @SerialName("workspace_id") val workspaceId: String,
    val cursor: Double,
    val transcripts: List<WireTranscript>,
)

@Serializable
data class WireTranscript(
    val id: String,
    @SerialName("_workspace_id") val workspaceId: String? = null,
    @SerialName("audio_path") val audioPath: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Double? = null,
    val language: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val models: WireModels = WireModels(),
    val speakers: Map<String, String> = emptyMap(),
    val segments: List<WireSegment> = emptyList(),
    /**
     * Raw JSON for the transcript doc. Filled in by [SyncClient] before
     * handing off to the ingest layer so the local Room row can keep a
     * verbatim copy for forward-compat (CRDT clocks, history, future
     * additive fields).
     */
    val rawJson: String = "",
)

@Serializable
data class WireModels(
    val asr: String? = null,
    val diarizer: String? = null,
)

@Serializable
data class WireSegment(
    val start: Double,
    val end: Double,
    val text: String,
    @SerialName("speaker_id") val speakerId: String? = null,
)

/** Optional CRDT fields kept untyped here; the CRDT layer parses them. */
@Serializable
internal data class WireRawTranscriptDoc(
    val id: String? = null,
    @SerialName("_clocks") val clocks: JsonElement? = null,
    @SerialName("_history") val history: JsonElement? = null,
)
