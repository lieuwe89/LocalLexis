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
        assertFalse(store.isPaired())
    }

    @Test fun put_then_get() {
        store.put("https://hub.local:8443", "ws_42")
        assertEquals("https://hub.local:8443", store.getHubUrl())
        assertEquals("ws_42", store.getWorkspaceId())
        assertTrue(store.isPaired())
    }

    @Test fun clear_resets() {
        store.put("https://h", "ws")
        store.clear()
        assertNull(store.getHubUrl())
        assertNull(store.getWorkspaceId())
        assertFalse(store.isPaired())
    }
}
