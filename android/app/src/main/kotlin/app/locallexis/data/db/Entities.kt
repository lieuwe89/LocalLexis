package app.locallexis.data.db

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Fts4
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "transcripts",
    indices = [Index("createdAt"), Index("jsonMtime")],
)
data class TranscriptEntity(
    @PrimaryKey val id: String,
    val workspaceId: String,
    val audioPath: String?,
    val audioBasename: String?,
    val durationSeconds: Double?,
    val language: String?,
    val createdAt: String?,
    val jsonMtime: Double,
    val modelsAsr: String?,
    val modelsDiarizer: String?,
    val title: String? = null,
    val summary: String? = null,
    val summaryModel: String? = null,
    val summaryCreatedAt: String? = null,
    val rawJson: String,
)

@Entity(
    tableName = "segments",
    primaryKeys = ["transcriptId", "segmentIndex"],
    indices = [Index("transcriptId"), Index("speakerId")],
    foreignKeys = [
        ForeignKey(
            entity = TranscriptEntity::class,
            parentColumns = ["id"],
            childColumns = ["transcriptId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
)
data class SegmentEntity(
    val transcriptId: String,
    val segmentIndex: Int,
    val startSec: Double,
    val endSec: Double,
    val text: String,
    val speakerId: String?,
)

@Fts4(notIndexed = ["transcriptId", "segmentIndex"])
@Entity(tableName = "segments_fts")
data class SegmentFtsEntity(
    val transcriptId: String,
    val segmentIndex: Int,
    val text: String,
)

@Entity(
    tableName = "speakers",
    primaryKeys = ["transcriptId", "speakerId"],
    foreignKeys = [
        ForeignKey(
            entity = TranscriptEntity::class,
            parentColumns = ["id"],
            childColumns = ["transcriptId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
)
data class SpeakerEntity(
    val transcriptId: String,
    val speakerId: String,
    val name: String,
)

@Entity(tableName = "devices")
data class DeviceEntity(
    @PrimaryKey val deviceId: String,
    val name: String,
    val pubkeyB64: String,
    val pairedAt: String,
    val lastSeen: String?,
)

@Entity(tableName = "sync_state")
data class SyncStateEntity(
    @PrimaryKey val workspaceId: String,
    val cursor: Double,
    val lastSyncAt: String?,
)
