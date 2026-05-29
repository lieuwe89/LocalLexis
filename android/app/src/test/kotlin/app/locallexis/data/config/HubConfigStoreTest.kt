package app.locallexis.data.config

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class HubConfigStoreTest {
    private lateinit var store: PrefsHubConfigStore

    @Before fun setup() {
        val ctx = ApplicationProvider.getApplicationContext<Context>()
        val prefs = ctx.getSharedPreferences("hubcfg_test", Context.MODE_PRIVATE)
        prefs.edit().clear().commit()
        store = PrefsHubConfigStore(prefs)
    }

    @Test fun empty_initially() {
        assertNull(store.getHubUrl())
        assertNull(store.getWorkspaceId())
        assertNull(store.getTlsSpkiB64())
        assertFalse(store.isPaired())
    }

    @Test fun put_then_get() {
        store.put("https://hub.local:8443", "ws_42")
        assertEquals("https://hub.local:8443", store.getHubUrl())
        assertEquals("ws_42", store.getWorkspaceId())
        assertNull(store.getTlsSpkiB64())
        assertTrue(store.isPaired())
    }

    @Test fun put_persists_spki_pin() {
        store.put("https://hub.local:8443", "ws_42", "PIN_B64==")
        assertEquals("PIN_B64==", store.getTlsSpkiB64())
    }

    @Test fun put_with_null_spki_clears_prior_pin() {
        store.put("https://h", "ws", "OLD==")
        store.put("http://h", "ws")
        assertNull(store.getTlsSpkiB64())
    }

    @Test fun clear_resets() {
        store.put("https://h", "ws", "PIN==")
        store.clear()
        assertNull(store.getHubUrl())
        assertNull(store.getWorkspaceId())
        assertNull(store.getTlsSpkiB64())
        assertFalse(store.isPaired())
    }
}
