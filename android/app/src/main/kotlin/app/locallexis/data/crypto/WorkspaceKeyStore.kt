package app.locallexis.data.crypto

import android.content.SharedPreferences
import android.util.Base64

/**
 * Persistent store for the workspace symmetric key W that the hub
 * sealedboxes back to the device during pairing. Real impl is
 * [EncryptedPrefsWorkspaceKeyStore] (Android Keystore-backed); tests use
 * [InMemoryWorkspaceKeyStore].
 */
interface WorkspaceKeyStore {
    fun get(): ByteArray?
    fun put(key: ByteArray)
    fun clear()
}

class InMemoryWorkspaceKeyStore : WorkspaceKeyStore {
    @Volatile
    private var key: ByteArray? = null

    override fun get(): ByteArray? = key?.copyOf()

    override fun put(key: ByteArray) {
        this.key = key.copyOf()
    }

    override fun clear() {
        key = null
    }
}

/**
 * EncryptedSharedPreferences-backed store. The master key wrapping the
 * preferences file lives in the Android Keystore (hardware-backed where
 * available). Workspace key is base64-encoded inside the encrypted prefs
 * because EncryptedSharedPreferences only exposes String/StringSet/etc.,
 * not raw bytes.
 */
class EncryptedPrefsWorkspaceKeyStore(
    private val prefs: SharedPreferences,
) : WorkspaceKeyStore {

    override fun get(): ByteArray? {
        val encoded = prefs.getString(KEY, null) ?: return null
        return Base64.decode(encoded, Base64.NO_WRAP)
    }

    override fun put(key: ByteArray) {
        val encoded = Base64.encodeToString(key, Base64.NO_WRAP)
        prefs.edit().putString(KEY, encoded).apply()
    }

    override fun clear() {
        prefs.edit().remove(KEY).apply()
    }

    companion object {
        private const val KEY = "workspace_key_b64"
    }
}
