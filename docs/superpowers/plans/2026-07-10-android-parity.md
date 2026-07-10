# Android Read-Only Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display hub-side renames (`title`), edited segment text, LLM summaries, and date+time in the Android app, synced read-only from the hub.

**Architecture:** The hub's `/sync/snapshot` already ships full transcript JSON docs including `title`, `summary`, `summary_meta`, and edited segment text. We extend the wire model + Room schema (migration 1→2) to carry the new fields, and update the three display surfaces (library list, search results, transcript detail). A lightweight in-app markdown renderer (no new dependency) displays summaries. No write path — Android stays read-only.

**Tech Stack:** Kotlin, Jetpack Compose, Room 2.6 (KSP, exported schemas), kotlinx-serialization, JUnit4 + Robolectric.

**Spec:** `docs/superpowers/specs/2026-07-10-android-parity-design.md`

**Build environment:** system Java is 1.8 — all Gradle commands must run under Android Studio's JBR:

```bash
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
cd /Users/lieuwejongsma/SpeechToText/android
```

All `./gradlew` commands below assume this. Run tests with `./gradlew :app:testDebugUnitTest --tests "<pattern>"`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `data/sync/WireModels.kt` | modify | + `title`, `summary`, `summaryMeta` on `WireTranscript`; new `WireSummaryMeta` |
| `data/db/Entities.kt` | modify | + 4 nullable columns on `TranscriptEntity` |
| `data/db/LocalLexisDatabase.kt` | modify | version 2, `MIGRATION_1_2`, `addMigrations` |
| `data/sync/SyncIngest.kt` | modify | map new wire fields to entity |
| `ui/format/Formatting.kt` | modify | + `formatDateTime`, + `displayTitle` |
| `ui/format/Markdown.kt` | create | pure markdown parser (blocks + spans), JVM-testable |
| `ui/components/MarkdownText.kt` | create | Compose renderer for parsed markdown |
| `features/transcript/SummaryCard.kt` | create | collapsible summary card |
| `features/transcript/TranscriptDetailScreen.kt` | modify | title, date+time, summary card |
| `features/library/LibraryScreen.kt` | modify | title + date+time in rows and search results |
| `ui/library/LibraryViewModel.kt` | modify | `TranscriptSummary` gains `title` |

Test files: `WireTranscriptFieldsTest.kt` (create), `MigrationTest.kt` (modify + new `Migration1To2Test`), `SyncIngestTest.kt` (modify), `FormattingTest.kt` (modify), `MarkdownTest.kt` (create).

All Kotlin paths below are relative to `android/app/src/{main,test}/kotlin/app/locallexis/`.

---

### Task 1: Wire model — title, summary, summary_meta

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/data/sync/WireModels.kt`
- Test: `android/app/src/test/kotlin/app/locallexis/data/sync/WireTranscriptFieldsTest.kt` (create)

- [ ] **Step 1: Write the failing test**

Create `WireTranscriptFieldsTest.kt`:

```kotlin
package app.locallexis.data.sync

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WireTranscriptFieldsTest {

    // Same settings as SyncClient's Json instance.
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Test
    fun parsesTitleSummaryAndMeta() {
        val doc = """
            {"id":"t1","title":"Council meeting","summary":"# Recap\n- first item",
             "summary_meta":{"model":"Qwen3-30B-A3B-Instruct-2507-GGUF","provider":"lemonade",
             "created_at":"2026-07-09T12:00:00Z"}}
        """.trimIndent()

        val parsed = json.decodeFromString(WireTranscript.serializer(), doc)

        assertEquals("Council meeting", parsed.title)
        assertEquals("# Recap\n- first item", parsed.summary)
        assertEquals("Qwen3-30B-A3B-Instruct-2507-GGUF", parsed.summaryMeta?.model)
        assertEquals("2026-07-09T12:00:00Z", parsed.summaryMeta?.createdAt)
    }

    @Test
    fun absentFieldsAreNull() {
        val parsed = json.decodeFromString(WireTranscript.serializer(), """{"id":"t1"}""")
        assertNull(parsed.title)
        assertNull(parsed.summary)
        assertNull(parsed.summaryMeta)
    }

    @Test
    fun metaWithMissingKeysYieldsNullMembers() {
        val parsed = json.decodeFromString(
            WireTranscript.serializer(),
            """{"id":"t1","summary":"text","summary_meta":{}}""",
        )
        assertEquals("text", parsed.summary)
        assertNull(parsed.summaryMeta?.model)
        assertNull(parsed.summaryMeta?.createdAt)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.sync.WireTranscriptFieldsTest"`
Expected: compilation FAILURE — `title`, `summary`, `summaryMeta` unresolved on `WireTranscript`.

- [ ] **Step 3: Implement**

In `WireModels.kt`, add three properties to `WireTranscript` after `segments` (before `rawJson`):

```kotlin
    val title: String? = null,
    val summary: String? = null,
    @SerialName("summary_meta") val summaryMeta: WireSummaryMeta? = null,
```

And add below `WireModels`:

```kotlin
/** Subset of the hub's summary_meta we display; `provider` is unused on mobile. */
@Serializable
data class WireSummaryMeta(
    val model: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.sync.WireTranscriptFieldsTest"`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/data/sync/WireModels.kt \
        app/src/test/kotlin/app/locallexis/data/sync/WireTranscriptFieldsTest.kt
git commit -m "feat(android): parse title/summary/summary_meta from sync docs"
```

---

### Task 2: Room schema v2 — new columns + migration

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/data/db/Entities.kt`
- Modify: `android/app/src/main/kotlin/app/locallexis/data/db/LocalLexisDatabase.kt`
- Test: `android/app/src/test/kotlin/app/locallexis/data/db/MigrationTest.kt` (extend)
- Test: `android/app/src/test/kotlin/app/locallexis/data/db/Migration1To2Test.kt` (create)

- [ ] **Step 1: Write the failing migration test**

Create `Migration1To2Test.kt`. `MigrationTestHelper` reads exported schema JSON from test assets — `sourceSets["test"].assets.srcDir("$projectDir/schemas")` is already configured in `app/build.gradle.kts`, and `androidx.room:room-testing` is already a test dependency.

```kotlin
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
```

- [ ] **Step 2: Extend the schema-export test**

In `MigrationTest.kt`, add inside the class:

```kotlin
    @Test
    fun schemaV2IsExported() {
        val schema = File(SCHEMA_DIR, "2.json")
        assertTrue(
            "v2 schema missing at ${schema.absolutePath} — bump @Database version and rebuild.",
            schema.exists(),
        )
        val text = schema.readText()
        for (column in listOf("title", "summary", "summaryModel", "summaryCreatedAt")) {
            assertTrue("v2 schema missing column '$column'", text.contains("\"columnName\": \"$column\""))
        }
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.db.Migration1To2Test" --tests "app.locallexis.data.db.MigrationTest"`
Expected: compilation FAILURE — `MIGRATION_1_2` unresolved.

- [ ] **Step 4: Implement entity columns**

In `Entities.kt`, add four properties to `TranscriptEntity` after `modelsDiarizer` (before `rawJson`). Defaults keep every existing named-arg construction site compiling:

```kotlin
    val title: String? = null,
    val summary: String? = null,
    val summaryModel: String? = null,
    val summaryCreatedAt: String? = null,
```

- [ ] **Step 5: Implement migration + version bump**

In `LocalLexisDatabase.kt`: change `version = 1` to `version = 2`, add imports:

```kotlin
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
```

In the companion object, add above `get`:

```kotlin
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE transcripts ADD COLUMN title TEXT")
                db.execSQL("ALTER TABLE transcripts ADD COLUMN summary TEXT")
                db.execSQL("ALTER TABLE transcripts ADD COLUMN summaryModel TEXT")
                db.execSQL("ALTER TABLE transcripts ADD COLUMN summaryCreatedAt TEXT")
            }
        }
```

And in `build()`, register it:

```kotlin
            Room.databaseBuilder(
                context.applicationContext,
                LocalLexisDatabase::class.java,
                "locallexis.db",
            ).addMigrations(MIGRATION_1_2).build()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.db.Migration1To2Test" --tests "app.locallexis.data.db.MigrationTest"`
Expected: PASS (the build regenerates `schemas/.../2.json` via KSP before tests run).

- [ ] **Step 7: Run the full DB test package to catch regressions**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.db.*"`
Expected: PASS (DaoTest, FtsTest untouched — new columns have defaults).

- [ ] **Step 8: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/data/db/Entities.kt \
        app/src/main/kotlin/app/locallexis/data/db/LocalLexisDatabase.kt \
        app/src/test/kotlin/app/locallexis/data/db/MigrationTest.kt \
        app/src/test/kotlin/app/locallexis/data/db/Migration1To2Test.kt \
        app/schemas/app.locallexis.data.db.LocalLexisDatabase/2.json
git commit -m "feat(android): room v2 schema with title/summary columns + 1->2 migration"
```

---

### Task 3: Sync ingest maps the new fields

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/data/sync/SyncIngest.kt`
- Test: `android/app/src/test/kotlin/app/locallexis/data/sync/SyncIngestTest.kt` (extend)

- [ ] **Step 1: Write the failing test**

Add to `SyncIngestTest.kt`:

```kotlin
    @Test
    fun ingestMapsTitleAndSummaryColumns() = runTest {
        ingest.applySnapshot(
            SyncResponse(
                workspaceId = "ws_a",
                cursor = 300.0,
                transcripts = listOf(
                    makeWire("t1", segments = emptyList()).copy(
                        title = "Renamed on web",
                        summary = "# Recap\n- item",
                        summaryMeta = WireSummaryMeta(
                            model = "Qwen3-30B",
                            createdAt = "2026-07-09T12:00:00Z",
                        ),
                    ),
                ),
            )
        )

        val stored = db.transcriptDao().getById("t1")!!
        assertEquals("Renamed on web", stored.title)
        assertEquals("# Recap\n- item", stored.summary)
        assertEquals("Qwen3-30B", stored.summaryModel)
        assertEquals("2026-07-09T12:00:00Z", stored.summaryCreatedAt)
    }

    @Test
    fun ingestWithoutNewFieldsStoresNulls() = runTest {
        ingest.applySnapshot(
            SyncResponse(
                workspaceId = "ws_a",
                cursor = 400.0,
                transcripts = listOf(makeWire("t2", segments = emptyList())),
            )
        )

        val stored = db.transcriptDao().getById("t2")!!
        org.junit.Assert.assertNull(stored.title)
        org.junit.Assert.assertNull(stored.summary)
        org.junit.Assert.assertNull(stored.summaryModel)
        org.junit.Assert.assertNull(stored.summaryCreatedAt)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.sync.SyncIngestTest"`
Expected: `ingestMapsTitleAndSummaryColumns` FAILS (`title` is null — ingest drops the fields). `ingestWithoutNewFieldsStoresNulls` passes already; keep it as the regression guard.

- [ ] **Step 3: Implement**

In `SyncIngest.upsertOne`, add to the `TranscriptEntity(...)` construction after `modelsDiarizer = doc.models.diarizer,`:

```kotlin
                title = doc.title,
                summary = doc.summary,
                summaryModel = doc.summaryMeta?.model,
                summaryCreatedAt = doc.summaryMeta?.createdAt,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.data.sync.SyncIngestTest"`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/data/sync/SyncIngest.kt \
        app/src/test/kotlin/app/locallexis/data/sync/SyncIngestTest.kt
git commit -m "feat(android): ingest title/summary fields into room columns"
```

---

### Task 4: `formatDateTime` + `displayTitle` formatters

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/ui/format/Formatting.kt`
- Test: `android/app/src/test/kotlin/app/locallexis/ui/format/FormattingTest.kt` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `FormattingTest.kt` (plus `import java.time.ZoneId` at the top):

```kotlin
    // formatDateTime — zone-pinned so results don't depend on the test machine.
    private val ams: ZoneId = ZoneId.of("Europe/Amsterdam")

    @Test fun datetime_iso_z_converts_to_zone() =
        assertEquals("May 12, 2026, 16:32", formatDateTime("2026-05-12T14:32:00Z", ams))
    @Test fun datetime_offsetless_kept_as_wall_clock() =
        assertEquals("May 12, 2026, 14:32", formatDateTime("2026-05-12T14:32:00", ams))
    @Test fun datetime_dateonly_renders_date_only() =
        assertEquals("May 12, 2026", formatDateTime("2026-05-12", ams))
    @Test fun datetime_garbage_passthrough() =
        assertEquals("not-a-date", formatDateTime("not-a-date", ams))
    @Test fun datetime_null_is_blank() = assertEquals("", formatDateTime(null, ams))
    @Test fun datetime_blank_is_blank() = assertEquals("", formatDateTime("", ams))

    // displayTitle fallback chain
    @Test fun title_wins() = assertEquals("Renamed", displayTitle("Renamed", "file-stem", "id1"))
    @Test fun blank_title_falls_to_basename() = assertEquals("file-stem", displayTitle(" ", "file-stem", "id1"))
    @Test fun null_title_falls_to_basename() = assertEquals("file-stem", displayTitle(null, "file-stem", "id1"))
    @Test fun no_title_no_basename_falls_to_id() = assertEquals("id1", displayTitle(null, null, "id1"))
    @Test fun blank_basename_falls_to_id() = assertEquals("id1", displayTitle(null, "", "id1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.ui.format.FormattingTest"`
Expected: compilation FAILURE — `formatDateTime`, `displayTitle` unresolved.

- [ ] **Step 3: Implement**

In `Formatting.kt`, add `import java.time.ZoneId` and:

```kotlin
private val DATETIME_OUT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("MMM d, yyyy, HH:mm", Locale.US)

/**
 * ISO-8601 -> "MMM d, yyyy, HH:mm". Offset timestamps are converted to
 * [zone] (device-local by default); offset-less ones render as wall-clock;
 * date-only input renders date-only. Unparseable -> raw; null/blank -> "".
 */
fun formatDateTime(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String {
    if (iso.isNullOrBlank()) return ""
    return try {
        OffsetDateTime.parse(iso).atZoneSameInstant(zone).format(DATETIME_OUT)
    } catch (_: DateTimeParseException) {
        try {
            LocalDateTime.parse(iso).format(DATETIME_OUT)
        } catch (_: DateTimeParseException) {
            try {
                LocalDate.parse(iso).format(DATE_OUT)
            } catch (_: DateTimeParseException) {
                iso
            }
        }
    }
}

/** Display name for a transcript: hub title -> audio filename stem -> id. */
fun displayTitle(title: String?, audioBasename: String?, id: String): String =
    title?.takeIf { it.isNotBlank() }
        ?: audioBasename?.takeIf { it.isNotBlank() }
        ?: id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.ui.format.FormattingTest"`
Expected: all PASS (old `formatDate` tests included).

- [ ] **Step 5: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/ui/format/Formatting.kt \
        app/src/test/kotlin/app/locallexis/ui/format/FormattingTest.kt
git commit -m "feat(android): formatDateTime and displayTitle helpers"
```

---

### Task 5: Library list + search results show title and date+time

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/ui/library/LibraryViewModel.kt`
- Modify: `android/app/src/main/kotlin/app/locallexis/features/library/LibraryScreen.kt`
- Test: `android/app/src/test/kotlin/app/locallexis/ui/LibraryViewModelTest.kt` (extend)

- [ ] **Step 1: Write the failing test**

In `LibraryViewModelTest.kt`, find the `private fun transcript(id, basename, createdAt)` helper (line ~143) and add a test that the projection carries `title`. Adapt to the file's existing collection style (it drives `uiState` via the fake DAO flow):

```kotlin
    @Test
    fun projectionCarriesTitle() {
        val entity = transcript("t1", "stem", "2026-07-01T10:00:00Z").copy(title = "Renamed")
        val summary = TranscriptSummary.fromEntity(entity)
        assertEquals("Renamed", summary.title)
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.ui.LibraryViewModelTest"`
Expected: compilation FAILURE — `summary.title` unresolved.

- [ ] **Step 3: Implement projection**

In `LibraryViewModel.kt`, `TranscriptSummary` gains `title` (first field after `id`) and the mapping:

```kotlin
data class TranscriptSummary(
    val id: String,
    val title: String?,
    val audioBasename: String?,
    val language: String?,
    val createdAt: String?,
    val durationSeconds: Double?,
) {
    companion object {
        fun fromEntity(e: TranscriptEntity) = TranscriptSummary(
            id = e.id,
            title = e.title,
            audioBasename = e.audioBasename,
            language = e.language,
            createdAt = e.createdAt,
            durationSeconds = e.durationSeconds,
        )
    }
}
```

- [ ] **Step 4: Implement screen changes**

In `LibraryScreen.kt`:

1. Add imports:

```kotlin
import app.locallexis.ui.format.displayTitle
import app.locallexis.ui.format.formatDateTime
```

2. `TranscriptRow` — title text becomes:

```kotlin
                text = displayTitle(item.title, item.audioBasename, item.id),
```

and in the `meta` list, `formatDate(item.createdAt)` becomes `formatDateTime(item.createdAt)`. Remove the now-unused `formatDate` import if no other caller remains in the file.

3. `rememberTitleResolver` — the associate lambda becomes:

```kotlin
            ?.associate { it.id to displayTitle(it.title, it.audioBasename, it.id) }
```

4. Preview data — `TranscriptSummary` gained a `title` param; update `previewItems` so positional construction still compiles and one row demonstrates a rename:

```kotlin
private val previewItems = listOf(
    TranscriptSummary("1", "Parks budget hearing", "council-2026-05-12", "en", "2026-05-12T14:32:00Z", 872.0),
    TranscriptSummary("2", null, "deposition-ramirez", "es", "2026-05-10T09:00:00Z", 3737.0),
    TranscriptSummary("3", null, "standup-0508", "en", "2026-05-08T08:45:00Z", 525.0),
)
```

- [ ] **Step 5: Run tests + compile check**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.ui.LibraryViewModelTest" :app:compileDebugKotlin`
Expected: PASS, no compile errors anywhere (search for other `TranscriptSummary(` construction sites if it fails).

- [ ] **Step 6: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/ui/library/LibraryViewModel.kt \
        app/src/main/kotlin/app/locallexis/features/library/LibraryScreen.kt \
        app/src/test/kotlin/app/locallexis/ui/LibraryViewModelTest.kt
git commit -m "feat(android): show synced titles and date+time in library list"
```

---

### Task 6: Markdown parser (pure Kotlin)

**Files:**
- Create: `android/app/src/main/kotlin/app/locallexis/ui/format/Markdown.kt`
- Test: `android/app/src/test/kotlin/app/locallexis/ui/format/MarkdownTest.kt` (create)

- [ ] **Step 1: Write the failing tests**

Create `MarkdownTest.kt`:

```kotlin
package app.locallexis.ui.format

import org.junit.Assert.assertEquals
import org.junit.Test

class MarkdownTest {

    @Test
    fun headingLevels() {
        val blocks = parseMarkdown("# One\n## Two\n### Three")
        assertEquals(
            listOf(1, 2, 3),
            blocks.map { (it as MdBlock.Heading).level },
        )
        assertEquals("One", (blocks[0] as MdBlock.Heading).spans.single().text)
    }

    @Test
    fun bulletAndOrderedLists() {
        val blocks = parseMarkdown("- alpha\n* beta\n1. gamma\n12. delta")
        val items = blocks.map { it as MdBlock.ListItem }
        assertEquals(listOf("•", "•", "1.", "12."), items.map { it.marker })
        assertEquals(listOf(false, false, true, true), items.map { it.ordered })
        assertEquals("alpha", items[0].spans.single().text)
    }

    @Test
    fun boldAndItalicSpans() {
        val spans = parseSpans("plain **bold** and *ital* end")
        assertEquals(
            listOf(
                MdSpan("plain "),
                MdSpan("bold", bold = true),
                MdSpan(" and "),
                MdSpan("ital", italic = true),
                MdSpan(" end"),
            ),
            spans,
        )
    }

    @Test
    fun unterminatedMarkersRenderLiterally() {
        assertEquals(listOf(MdSpan("a **b and c")), parseSpans("a **b and c"))
    }

    @Test
    fun boldLineIsNotABullet() {
        val block = parseMarkdown("**Key point** here").single()
        val spans = (block as MdBlock.Paragraph).spans
        assertEquals(MdSpan("Key point", bold = true), spans[0])
        assertEquals(MdSpan(" here"), spans[1])
    }

    @Test
    fun blankLinesDropped_plainLinesAreParagraphs() {
        val blocks = parseMarkdown("first\n\nsecond\n")
        assertEquals(2, blocks.size)
        assertEquals("first", (blocks[0] as MdBlock.Paragraph).spans.single().text)
    }

    @Test
    fun fourHashesIsPlainText() {
        val block = parseMarkdown("#### deep heading").single()
        assertEquals("#### deep heading", (block as MdBlock.Paragraph).spans.single().text)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.ui.format.MarkdownTest"`
Expected: compilation FAILURE — `parseMarkdown` etc. unresolved.

- [ ] **Step 3: Implement**

Create `Markdown.kt`:

```kotlin
package app.locallexis.ui.format

/**
 * Minimal line-oriented markdown model for LLM summaries. Covers the
 * subset the summarizer actually emits — #/##/### headings, bullet and
 * numbered list items, **bold**, *italic*. Anything else passes through
 * as plain paragraph text. Deliberately not a spec-compliant parser;
 * see the design doc (2026-07-10-android-parity-design.md).
 */
sealed interface MdBlock {
    data class Heading(val level: Int, val spans: List<MdSpan>) : MdBlock
    data class Paragraph(val spans: List<MdSpan>) : MdBlock
    data class ListItem(val ordered: Boolean, val marker: String, val spans: List<MdSpan>) : MdBlock
}

data class MdSpan(val text: String, val bold: Boolean = false, val italic: Boolean = false)

private val HEADING = Regex("""^(#{1,3})\s+(.*)$""")
private val BULLET = Regex("""^[-*]\s+(.*)$""")
private val ORDERED = Regex("""^(\d+)\.\s+(.*)$""")

fun parseMarkdown(text: String): List<MdBlock> =
    text.lines().mapNotNull { raw ->
        val line = raw.trim()
        if (line.isEmpty()) return@mapNotNull null
        HEADING.matchEntire(line)?.let {
            return@mapNotNull MdBlock.Heading(it.groupValues[1].length, parseSpans(it.groupValues[2]))
        }
        BULLET.matchEntire(line)?.let {
            return@mapNotNull MdBlock.ListItem(false, "•", parseSpans(it.groupValues[1]))
        }
        ORDERED.matchEntire(line)?.let {
            return@mapNotNull MdBlock.ListItem(true, "${it.groupValues[1]}.", parseSpans(it.groupValues[2]))
        }
        MdBlock.Paragraph(parseSpans(line))
    }

fun parseSpans(line: String): List<MdSpan> {
    val spans = mutableListOf<MdSpan>()
    val sb = StringBuilder()
    fun flush() {
        if (sb.isNotEmpty()) {
            spans.add(MdSpan(sb.toString()))
            sb.clear()
        }
    }
    var i = 0
    while (i < line.length) {
        when {
            line.startsWith("**", i) -> {
                val end = line.indexOf("**", i + 2)
                if (end == -1) { sb.append(line[i]); i++ } else {
                    flush()
                    spans.add(MdSpan(line.substring(i + 2, end), bold = true))
                    i = end + 2
                }
            }
            line[i] == '*' -> {
                val end = line.indexOf('*', i + 1)
                if (end == -1) { sb.append(line[i]); i++ } else {
                    flush()
                    spans.add(MdSpan(line.substring(i + 1, end), italic = true))
                    i = end + 1
                }
            }
            else -> { sb.append(line[i]); i++ }
        }
    }
    flush()
    return spans
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./gradlew :app:testDebugUnitTest --tests "app.locallexis.ui.format.MarkdownTest"`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/ui/format/Markdown.kt \
        app/src/test/kotlin/app/locallexis/ui/format/MarkdownTest.kt
git commit -m "feat(android): lightweight markdown parser for summaries"
```

---

### Task 7: MarkdownText composable + SummaryCard

Compose rendering is verified via `@Preview` + the batched device session (project has no Compose UI test rig); the logic lives in the Task 6 parser, already unit-tested.

**Files:**
- Create: `android/app/src/main/kotlin/app/locallexis/ui/components/MarkdownText.kt`
- Create: `android/app/src/main/kotlin/app/locallexis/features/transcript/SummaryCard.kt`

- [ ] **Step 1: Create `MarkdownText.kt`**

```kotlin
package app.locallexis.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import app.locallexis.ui.format.MdBlock
import app.locallexis.ui.format.MdSpan
import app.locallexis.ui.format.parseMarkdown

/** Renders the markdown subset produced by [parseMarkdown]. */
@Composable
fun MarkdownText(markdown: String, modifier: Modifier = Modifier) {
    val blocks = remember(markdown) { parseMarkdown(markdown) }
    Column(modifier) {
        blocks.forEach { block ->
            when (block) {
                is MdBlock.Heading -> Text(
                    text = annotate(block.spans),
                    style = when (block.level) {
                        1 -> MaterialTheme.typography.titleMedium
                        2 -> MaterialTheme.typography.titleSmall
                        else -> MaterialTheme.typography.labelLarge
                    },
                    modifier = Modifier.padding(top = 8.dp, bottom = 2.dp),
                )
                is MdBlock.ListItem -> Row(Modifier.padding(vertical = 1.dp)) {
                    Text(
                        text = block.marker,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(end = 6.dp),
                    )
                    Text(annotate(block.spans), style = MaterialTheme.typography.bodyMedium)
                }
                is MdBlock.Paragraph -> Text(
                    text = annotate(block.spans),
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(vertical = 2.dp),
                )
            }
        }
    }
}

private fun annotate(spans: List<MdSpan>): AnnotatedString = buildAnnotatedString {
    spans.forEach { s ->
        withStyle(
            SpanStyle(
                fontWeight = if (s.bold) FontWeight.Bold else null,
                fontStyle = if (s.italic) FontStyle.Italic else null,
            )
        ) { append(s.text) }
    }
}
```

- [ ] **Step 2: Create `SummaryCard.kt`**

```kotlin
package app.locallexis.features.transcript

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.locallexis.design.LocalLexisTheme
import app.locallexis.ui.components.MarkdownText
import app.locallexis.ui.format.formatDateTime

/** Collapsible card showing the hub-generated LLM summary. */
@Composable
fun SummaryCard(
    summary: String,
    model: String?,
    createdAt: String?,
    modifier: Modifier = Modifier,
) {
    var expanded by rememberSaveable { mutableStateOf(true) }
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Summary", style = MaterialTheme.typography.titleSmall)
                    val caption = listOfNotNull(
                        model,
                        formatDateTime(createdAt).ifBlank { null },
                    ).joinToString(" · ")
                    if (caption.isNotBlank()) {
                        Text(
                            text = caption,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Icon(
                    imageVector = if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = if (expanded) "Collapse summary" else "Expand summary",
                )
            }
            if (expanded) {
                MarkdownText(summary, Modifier.padding(top = 6.dp))
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun SummaryCardPreview() {
    LocalLexisTheme {
        SummaryCard(
            summary = "# Recap\nThe council **approved** the parks budget.\n" +
                "- Survey lands *next week*\n- 1. follow-up scheduled",
            model = "Qwen3-30B-A3B-Instruct-2507-GGUF",
            createdAt = "2026-07-09T12:00:00Z",
        )
    }
}
```

- [ ] **Step 3: Compile check**

Run: `./gradlew :app:compileDebugKotlin`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/ui/components/MarkdownText.kt \
        app/src/main/kotlin/app/locallexis/features/transcript/SummaryCard.kt
git commit -m "feat(android): markdown renderer and collapsible summary card"
```

---

### Task 8: Transcript detail — title, date+time, summary card

**Files:**
- Modify: `android/app/src/main/kotlin/app/locallexis/features/transcript/TranscriptDetailScreen.kt`

- [ ] **Step 1: Implement header + summary wiring**

In `TranscriptDetailScreen.kt`:

1. Replace the `formatDate` import with:

```kotlin
import app.locallexis.ui.format.displayTitle
import app.locallexis.ui.format.formatDateTime
```

2. In `DetailHeader`, the title `Text` becomes:

```kotlin
            text = displayTitle(transcript.title, transcript.audioBasename, transcript.id),
```

and in the `meta` list, `formatDate(transcript.createdAt)` becomes `formatDateTime(transcript.createdAt)`.

3. In `ReadyDetail`, render the summary as the first item of the existing `LazyColumn` (so it scrolls away with content):

```kotlin
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        ) {
            val summary = transcript.summary
            if (!summary.isNullOrBlank()) {
                item(key = "summary") {
                    SummaryCard(
                        summary = summary,
                        model = transcript.summaryModel,
                        createdAt = transcript.summaryCreatedAt,
                        modifier = Modifier.padding(vertical = 4.dp),
                    )
                }
            }
            items(segments, key = { it.index }) { seg ->
                SegmentBubble(seg)
            }
        }
```

4. Update the preview fixture so the summary path is preview-visible — in `previewTranscript`, use the entity's new defaulted params:

```kotlin
private val previewTranscript = TranscriptEntity(
    id = "1",
    workspaceId = "ws",
    audioPath = "/x/council-2026-05-12.wav",
    audioBasename = "council-2026-05-12",
    durationSeconds = 872.0,
    language = "en",
    createdAt = "2026-05-12T14:32:00Z",
    jsonMtime = 0.0,
    modelsAsr = null,
    modelsDiarizer = null,
    title = "Parks budget hearing",
    summary = "# Recap\nCouncil **tabled** the parks budget pending the survey.",
    summaryModel = "Qwen3-30B",
    summaryCreatedAt = "2026-07-09T12:00:00Z",
    rawJson = "{}",
)
```

- [ ] **Step 2: Compile + full test check**

Run: `./gradlew :app:compileDebugKotlin :app:testDebugUnitTest`
Expected: BUILD SUCCESSFUL, all unit tests PASS (TranscriptDetailViewModelTest untouched — entity defaults).

- [ ] **Step 3: Commit**

```bash
git add app/src/main/kotlin/app/locallexis/features/transcript/TranscriptDetailScreen.kt
git commit -m "feat(android): detail screen shows title, date+time and summary card"
```

---

### Task 9: Full verification + devlog

**Files:**
- Modify: `DEVLOG.md` (gitignored — do NOT commit)

- [ ] **Step 1: Full unit test suite**

Run: `./gradlew :app:testDebugUnitTest`
Expected: BUILD SUCCESSFUL, zero failures.

- [ ] **Step 2: Debug APK build**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL — APK at `app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 3: Update DEVLOG**

Append to the `## Running log` section of `/Users/lieuwejongsma/SpeechToText/DEVLOG.md` under a `### 2026-07-10` heading: what shipped (Android read-only parity), the key insight (sync already carried title/summary/edits on the wire — the app was dropping them at the parse layer), and the decision to hand-roll the markdown subset instead of adding a dependency. Do not commit it.

- [ ] **Step 4: Note deferred device checks**

Add to the batched manual-test list (DEVLOG entry is fine): install fresh APK over existing install (exercises migration 1→2 on real data), sync against homelab hub, verify a renamed + summarized + edited transcript renders correctly, verify old transcripts unaffected.

---

## Self-Review Notes

- Spec coverage: data layer (Tasks 1–3), title display (Tasks 4, 5, 8), date+time (Tasks 4, 5, 8), summary view + markdown (Tasks 6–8), testing (per task + Task 9). Reactivity section requires no change (spec §5).
- Version bump (`versionCode`/`versionName` in `app/build.gradle.kts`) is intentionally left to the push workflow per user's global git-push rule.
