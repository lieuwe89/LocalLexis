package app.locallexis.ui.format

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
}
