package app.locallexis.data.pairing

import android.content.SharedPreferences

/**
 * Persisted record of the hub-assigned device_id. Mirrors
 * [app.locallexis.data.crypto.WorkspaceKeyStore] in shape — the
 * production impl writes to EncryptedSharedPreferences, in-memory impl
 * is for tests.
 */
interface DeviceIdentityStore {
    fun getDeviceId(): String?
    fun putDeviceId(id: String)
    fun clear()
}

/**
 * SharedPreferences-backed store. The caller is responsible for passing
 * in EncryptedSharedPreferences for the production wiring. Plain
 * SharedPreferences also works (device_id is not secret on its own —
 * it's a hub-assigned opaque handle) but co-locating it with the
 * encrypted prefs file keeps the auth material in a single bag.
 */
class PrefsDeviceIdentityStore(
    private val prefs: SharedPreferences,
) : DeviceIdentityStore {

    override fun getDeviceId(): String? = prefs.getString(KEY, null)

    override fun putDeviceId(id: String) {
        prefs.edit().putString(KEY, id).apply()
    }

    override fun clear() {
        prefs.edit().remove(KEY).apply()
    }

    companion object {
        private const val KEY = "device_id"
    }
}
