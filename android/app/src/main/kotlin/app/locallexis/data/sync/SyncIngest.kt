package app.locallexis.data.sync

import androidx.room.withTransaction
import app.locallexis.data.db.LocalLexisDatabase
import app.locallexis.data.db.SegmentEntity
import app.locallexis.data.db.SpeakerEntity
import app.locallexis.data.db.SyncStateEntity
import app.locallexis.data.db.TranscriptEntity
import java.time.Instant

/**
 * Apply a [SyncResponse] to the Room library. Single @Transaction so a
 * sync that fails midway leaves the DB in its prior coherent state
 * (no half-imported transcript whose segments are missing).
 *
 * Cursor advance is part of the same transaction: a successful ingest
 * also commits the new cursor, so the next /sync/since starts from the
 * right place even if the process crashes immediately after the call.
 */
class SyncIngest(private val db: LocalLexisDatabase) {

    /** Read the persisted cursor for a workspace, or null if uninitialised. */
    suspend fun cursorFor(workspaceId: String): Double? =
        db.syncStateDao().getCursor(workspaceId)

    suspend fun applySnapshot(response: SyncResponse) {
        db.withTransaction {
            for (doc in response.transcripts) {
                upsertOne(doc, response.cursor)
            }
            db.syncStateDao().upsert(
                SyncStateEntity(
                    workspaceId = response.workspaceId,
                    cursor = response.cursor,
                    lastSyncAt = Instant.now().toString(),
                )
            )
        }
    }

    private suspend fun upsertOne(doc: WireTranscript, cursor: Double) {
        val audioBasename = doc.audioPath?.substringAfterLast('/')

        db.transcriptDao().upsert(
            TranscriptEntity(
                id = doc.id,
                workspaceId = doc.workspaceId ?: "",
                audioPath = doc.audioPath,
                audioBasename = audioBasename,
                durationSeconds = doc.durationSeconds,
                language = doc.language,
                createdAt = doc.createdAt,
                jsonMtime = cursor,
                modelsAsr = doc.models.asr,
                modelsDiarizer = doc.models.diarizer,
                rawJson = doc.rawJson,
            )
        )

        // Replace strategy on segments/speakers — full doc reload is the
        // semantics of /sync/snapshot. Incremental relabel ops will be
        // handled by the CRDT layer in a future block, not here.
        db.segmentDao().deleteForTranscript(doc.id)
        db.segmentDao().upsertAll(
            doc.segments.mapIndexed { idx, seg ->
                SegmentEntity(
                    transcriptId = doc.id,
                    segmentIndex = idx,
                    startSec = seg.start,
                    endSec = seg.end,
                    text = seg.text,
                    speakerId = seg.speakerId,
                )
            }
        )
        db.speakerDao().deleteForTranscript(doc.id)
        db.speakerDao().upsertAll(
            doc.speakers.map { (id, name) ->
                SpeakerEntity(transcriptId = doc.id, speakerId = id, name = name)
            }
        )
    }
}
