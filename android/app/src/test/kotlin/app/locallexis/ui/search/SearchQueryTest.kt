package app.locallexis.ui.search

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SearchQueryTest {

    @Test fun singleTermBecomesPrefix() {
        assertEquals("quick*", buildFtsMatchQuery("quick"))
    }

    @Test fun multipleTermsArePrefixedAndSpaceJoined() {
        assertEquals("quick* brown*", buildFtsMatchQuery("quick brown"))
    }

    @Test fun collapsesExtraWhitespace() {
        assertEquals("a* b*", buildFtsMatchQuery("  a    b  "))
    }

    @Test fun stripsFtsOperators() {
        assertEquals("hi* no* x*", buildFtsMatchQuery("\"hi\" -no (x)"))
    }

    @Test fun blankReturnsNull() {
        assertNull(buildFtsMatchQuery("   "))
    }

    @Test fun operatorOnlyReturnsNull() {
        assertNull(buildFtsMatchQuery("*() \"\""))
    }
}
