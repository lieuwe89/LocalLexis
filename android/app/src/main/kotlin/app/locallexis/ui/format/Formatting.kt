package app.locallexis.ui.format

import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

private val DATE_OUT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)

/** Seconds -> "m:ss" (under an hour) or "h:mm:ss". Null/NaN/negative -> "". */
fun formatDuration(seconds: Double?): String {
    if (seconds == null || seconds.isNaN() || seconds < 0) return ""
    val total = seconds.toInt()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) String.format(Locale.US, "%d:%02d:%02d", h, m, s)
    else String.format(Locale.US, "%d:%02d", m, s)
}

/**
 * ISO-8601 -> "MMM d, yyyy". Tries offset date-time, then offset-less
 * date-time, then date-only. Unparseable -> raw string; null/blank -> "".
 */
fun formatDate(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
    return try {
        OffsetDateTime.parse(iso).format(DATE_OUT)
    } catch (_: DateTimeParseException) {
        try {
            LocalDateTime.parse(iso).format(DATE_OUT)
        } catch (_: DateTimeParseException) {
            try {
                LocalDate.parse(iso).format(DATE_OUT)
            } catch (_: DateTimeParseException) {
                iso
            }
        }
    }
}
