package app.locallexis.data.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingPayloadTest {

    @Test
    fun parsesValidPayload() {
        val json = """
            {
              "hub_url": "https://192.168.1.50:8443",
              "workspace_id": "ws_8a3b1c2d4e5f",
              "token": "abc123def456",
              "tls_spki_b64": "Zm9vYmFy"
            }
        """.trimIndent()

        val payload = PairingPayloadV1.parse(json)

        assertEquals("https://192.168.1.50:8443", payload.hubUrl)
        assertEquals("ws_8a3b1c2d4e5f", payload.workspaceId)
        assertEquals("abc123def456", payload.token)
        assertEquals("Zm9vYmFy", payload.tlsSpkiB64)
    }

    @Test
    fun parsesPayloadWithoutOptionalTlsPin() {
        val json = """
            {
              "hub_url": "https://hub.local:8443",
              "workspace_id": "ws_xxx",
              "token": "tok"
            }
        """.trimIndent()

        val payload = PairingPayloadV1.parse(json)

        assertEquals("https://hub.local:8443", payload.hubUrl)
        assertNull(payload.tlsSpkiB64)
    }

    @Test
    fun rejectsMissingToken() {
        val json = """{"hub_url":"https://h","workspace_id":"w"}"""
        assertThrows(PairingPayloadException::class.java) {
            PairingPayloadV1.parse(json)
        }
    }

    @Test
    fun rejectsMissingHubUrl() {
        val json = """{"workspace_id":"w","token":"t"}"""
        assertThrows(PairingPayloadException::class.java) {
            PairingPayloadV1.parse(json)
        }
    }

    @Test
    fun rejectsMissingWorkspaceId() {
        val json = """{"hub_url":"https://h","token":"t"}"""
        assertThrows(PairingPayloadException::class.java) {
            PairingPayloadV1.parse(json)
        }
    }

    @Test
    fun rejectsBlankToken() {
        val json = """{"hub_url":"https://h","workspace_id":"w","token":""}"""
        assertThrows(PairingPayloadException::class.java) {
            PairingPayloadV1.parse(json)
        }
    }

    @Test
    fun rejectsNonHttpUrl() {
        val json = """{"hub_url":"ftp://h","workspace_id":"w","token":"t"}"""
        assertThrows(PairingPayloadException::class.java) {
            PairingPayloadV1.parse(json)
        }
    }

    @Test
    fun rejectsMalformedJson() {
        assertThrows(PairingPayloadException::class.java) {
            PairingPayloadV1.parse("{not json")
        }
    }

    @Test
    fun acceptsHttpForLocalDev() {
        // Useful for emulator + dev hub on http (TLS pin deferred).
        val json = """{"hub_url":"http://10.0.2.2:8000","workspace_id":"w","token":"t"}"""
        val payload = PairingPayloadV1.parse(json)
        assertEquals("http://10.0.2.2:8000", payload.hubUrl)
    }
}
