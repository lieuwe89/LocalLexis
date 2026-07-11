package app.locallexis.data.db

import androidx.room.testing.MigrationTestHelper
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class Migration1To2Test {

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        LocalLexisDatabase::class.java,
    )

    @Test
    fun migrate1To2PreservesRowsAndAddsNullColumns() {
        helper.createDatabase("migration-1-2-test", 1).apply {
            execSQL(
                "INSERT INTO transcripts (id, workspaceId, audioPath, audioBasename, " +
                    "durationSeconds, language, createdAt, jsonMtime, modelsAsr, " +
                    "modelsDiarizer, rawJson) " +
                    "VALUES ('t1', 'ws', NULL, 'meeting', NULL, 'en', " +
                    "'2026-07-01T10:00:00Z', 1.0, NULL, NULL, '{}')"
            )
            close()
        }

        val db = helper.runMigrationsAndValidate(
            "migration-1-2-test", 2, true, LocalLexisDatabase.MIGRATION_1_2,
        )

        db.query(
            "SELECT title, summary, summaryModel, summaryCreatedAt " +
                "FROM transcripts WHERE id = 't1'"
        ).use { c ->
            assertTrue("row t1 lost in migration", c.moveToFirst())
            for (i in 0..3) {
                assertTrue("column $i should be NULL after migration", c.isNull(i))
            }
        }
    }
}
