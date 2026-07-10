package app.locallexis.ui.format

import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Test

class FormattingTest {
    @Test fun duration_null_is_blank() = assertEquals("", formatDuration(null))
    @Test fun duration_nan_is_blank() = assertEquals("", formatDuration(Double.NaN))
    @Test fun duration_negative_is_blank() = assertEquals("", formatDuration(-5.0))
    @Test fun duration_zero() = assertEquals("0:00", formatDuration(0.0))
    @Test fun duration_under_hour() = assertEquals("1:05", formatDuration(65.0))
    @Test fun duration_over_hour() = assertEquals("1:01:01", formatDuration(3661.0))
    @Test fun date_iso_z() = assertEquals("May 12, 2026", formatDate("2026-05-12T14:32:00Z"))
    @Test fun date_offsetless_datetime() = assertEquals("May 12, 2026", formatDate("2026-05-12T14:32:00"))
    @Test fun date_dateonly() = assertEquals("May 12, 2026", formatDate("2026-05-12"))
    @Test fun date_garbage_passthrough() = assertEquals("not-a-date", formatDate("not-a-date"))
    @Test fun date_blank_is_blank() = assertEquals("", formatDate(""))
    @Test fun date_null_is_blank() = assertEquals("", formatDate(null))

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
}
