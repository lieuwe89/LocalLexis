package app.locallexis.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

data class SearchHit(
    val transcriptId: String,
    val segmentIndex: Int,
    val text: String,
    val snippet: String,
)

@Dao
interface TranscriptDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(transcript: TranscriptEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(transcripts: List<TranscriptEntity>)

    @Query("SELECT * FROM transcripts WHERE id = :id")
    suspend fun getById(id: String): TranscriptEntity?

    @Query("SELECT * FROM transcripts ORDER BY createdAt DESC")
    fun listAll(): Flow<List<TranscriptEntity>>

    @Query("DELETE FROM transcripts WHERE id = :id")
    suspend fun deleteById(id: String)
}

@Dao
abstract class SegmentDao {
    @Transaction
    open suspend fun upsertAll(segments: List<SegmentEntity>) {
        if (segments.isEmpty()) return
        val transcriptIds = segments.map { it.transcriptId }.toSet()
        for (tid in transcriptIds) {
            deleteFtsForTranscript(tid)
        }
        insertSegments(segments)
        insertFts(
            segments.map {
                SegmentFtsEntity(
                    transcriptId = it.transcriptId,
                    segmentIndex = it.segmentIndex,
                    text = it.text,
                )
            }
        )
    }

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    protected abstract suspend fun insertSegments(segments: List<SegmentEntity>)

    @Insert
    protected abstract suspend fun insertFts(rows: List<SegmentFtsEntity>)

    @Query("DELETE FROM segments_fts WHERE transcriptId = :transcriptId")
    protected abstract suspend fun deleteFtsForTranscript(transcriptId: String)

    @Query(
        "SELECT * FROM segments WHERE transcriptId = :transcriptId AND speakerId = :speakerId " +
            "ORDER BY startSec ASC"
    )
    abstract suspend fun bySpeaker(transcriptId: String, speakerId: String): List<SegmentEntity>

    @Query("SELECT * FROM segments WHERE transcriptId = :transcriptId ORDER BY segmentIndex ASC")
    abstract suspend fun forTranscript(transcriptId: String): List<SegmentEntity>

    @Transaction
    open suspend fun deleteForTranscript(transcriptId: String) {
        deleteFtsForTranscript(transcriptId)
        deleteSegmentsForTranscript(transcriptId)
    }

    @Query("DELETE FROM segments WHERE transcriptId = :transcriptId")
    protected abstract suspend fun deleteSegmentsForTranscript(transcriptId: String)

    @Query("SELECT COUNT(*) FROM segments_fts")
    abstract suspend fun countFts(): Int
}

@Dao
interface SpeakerDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(speakers: List<SpeakerEntity>)

    @Query("SELECT * FROM speakers WHERE transcriptId = :transcriptId")
    fun forTranscript(transcriptId: String): Flow<List<SpeakerEntity>>

    @Query("DELETE FROM speakers WHERE transcriptId = :transcriptId")
    suspend fun deleteForTranscript(transcriptId: String)
}

@Dao
interface DeviceDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(device: DeviceEntity)

    @Query("SELECT * FROM devices ORDER BY pairedAt DESC")
    fun listAll(): Flow<List<DeviceEntity>>

    @Query("DELETE FROM devices WHERE deviceId = :deviceId")
    suspend fun deleteById(deviceId: String)
}

@Dao
interface SyncStateDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(state: SyncStateEntity)

    @Query("SELECT cursor FROM sync_state WHERE workspaceId = :workspaceId")
    suspend fun getCursor(workspaceId: String): Double?

    @Query("SELECT * FROM sync_state WHERE workspaceId = :workspaceId")
    suspend fun get(workspaceId: String): SyncStateEntity?

    @Query("DELETE FROM sync_state")
    suspend fun deleteAll()
}

@Dao
interface SearchDao {
    @Query(
        "SELECT transcriptId, segmentIndex, text, " +
            "snippet(segments_fts, '[', ']', '...', -1, 16) AS snippet " +
            "FROM segments_fts WHERE segments_fts MATCH :query " +
            "ORDER BY transcriptId, segmentIndex"
    )
    suspend fun searchSegments(query: String): List<SearchHit>
}
