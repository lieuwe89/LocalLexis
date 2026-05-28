package app.locallexis.data.crypto

import android.content.Context
import android.content.SharedPreferences
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class EncryptedPrefsSecretStorageTest {
    private lateinit var prefs: SharedPreferences

    @Before fun setup() {
        val ctx = ApplicationProvider.getApplicationContext<Context>()
        prefs = ctx.getSharedPreferences("seed_test", Context.MODE_PRIVATE)
        prefs.edit().clear().commit()
    }

    @Test fun null_before_first_write() {
        assertNull(EncryptedPrefsSecretStorage(prefs).getSecretSeed())
    }

    @Test fun roundtrip_across_instances() {
        val seed = ByteArray(32) { it.toByte() }
        EncryptedPrefsSecretStorage(prefs).putSecretSeed(seed)
        // A fresh instance over the same prefs reads back the same bytes.
        assertArrayEquals(seed, EncryptedPrefsSecretStorage(prefs).getSecretSeed())
    }
}
