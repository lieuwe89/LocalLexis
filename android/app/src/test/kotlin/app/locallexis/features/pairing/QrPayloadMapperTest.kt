package app.locallexis.features.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class QrPayloadMapperTest {

    private val valid = """
        {"hub_url":"https://192.168.1.50:8443","workspace_id":"ws_a","token":"tok","tls_spki_b64":"PIN=="}
    """.trimIndent()

    @Test fun parsesValidPayload() {
        val result = qrToPayload(valid)
        assertTrue(result.isSuccess)
        val payload = result.getOrThrow()
        assertEquals("https://192.168.1.50:8443", payload.hubUrl)
        assertEquals("ws_a", payload.workspaceId)
        assertEquals("PIN==", payload.tlsSpkiB64)
    }

    @Test fun trimsSurroundingWhitespace() {
        assertTrue(qrToPayload("  $valid  ").isSuccess)
    }

    @Test fun failsOnGarbageWithoutThrowing() {
        val result = qrToPayload("not json")
        assertTrue(result.isFailure)
    }

    @Test fun failsOnMissingRequiredField() {
        val result = qrToPayload("""{"hub_url":"https://h","token":"t"}""")
        assertTrue(result.isFailure)
    }
}
