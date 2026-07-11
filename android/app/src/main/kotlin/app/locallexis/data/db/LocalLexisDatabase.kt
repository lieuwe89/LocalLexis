package app.locallexis.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        TranscriptEntity::class,
        SegmentEntity::class,
        SegmentFtsEntity::class,
        SpeakerEntity::class,
        DeviceEntity::class,
        SyncStateEntity::class,
    ],
    version = 2,
    exportSchema = true,
)
abstract class LocalLexisDatabase : RoomDatabase() {
    abstract fun transcriptDao(): TranscriptDao
    abstract fun segmentDao(): SegmentDao
    abstract fun speakerDao(): SpeakerDao
    abstract fun deviceDao(): DeviceDao
    abstract fun syncStateDao(): SyncStateDao
    abstract fun searchDao(): SearchDao

    companion object {
        @Volatile
        private var instance: LocalLexisDatabase? = null

        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE transcripts ADD COLUMN title TEXT")
                db.execSQL("ALTER TABLE transcripts ADD COLUMN summary TEXT")
                db.execSQL("ALTER TABLE transcripts ADD COLUMN summaryModel TEXT")
                db.execSQL("ALTER TABLE transcripts ADD COLUMN summaryCreatedAt TEXT")
            }
        }

        fun get(context: Context): LocalLexisDatabase =
            instance ?: synchronized(this) {
                instance ?: build(context).also { instance = it }
            }

        private fun build(context: Context): LocalLexisDatabase =
            Room.databaseBuilder(
                context.applicationContext,
                LocalLexisDatabase::class.java,
                "locallexis.db",
            ).addMigrations(MIGRATION_1_2).build()
    }
}
