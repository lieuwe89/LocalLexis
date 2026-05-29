package app.locallexis.ui.search

private val FTS_SPECIALS = Regex("[\"*^:()\\-]")
private val WHITESPACE = Regex("\\s+")

/**
 * Turn free text into a safe FTS4 MATCH expression. Strips the operator
 * characters FTS would otherwise interpret (quote, star, caret, colon, parens,
 * dash), then makes each surviving token a prefix term so search-as-you-type
 * matches partial words. Tokens are implicitly AND-ed by FTS. Returns null when
 * nothing searchable remains, so callers can short-circuit to "no results".
 */
fun buildFtsMatchQuery(input: String): String? {
    val tokens = input.trim()
        .split(WHITESPACE)
        .map { it.replace(FTS_SPECIALS, "") }
        .filter { it.isNotBlank() }
    if (tokens.isEmpty()) return null
    return tokens.joinToString(" ") { "$it*" }
}
