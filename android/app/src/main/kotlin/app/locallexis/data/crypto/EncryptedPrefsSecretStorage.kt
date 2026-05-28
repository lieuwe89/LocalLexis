package app.locallexis.data.crypto

import android.content.SharedPreferences
import android.util.Base64

/**
 * [SecretStorage] backed by a (production: Encrypted)SharedPreferences
 * file. Stores the raw 32-byte Ed25519 seed base64-encoded under a stable
 * key, mirroring [EncryptedPrefsWorkspaceKeyStore].
 */
class EncryptedPrefsSecretStorage(
    private val prefs: SharedPreferences,
) : SecretStorage {

    override fun getSecretSeed(): ByteArray? {
        val encoded = prefs.getString(KEY, null) ?: return null
        return Base64.decode(encoded, Base64.NO_WRAP)
    }

    override fun putSecretSeed(seed: ByteArray) {
        prefs.edit().putString(KEY, Base64.encodeToString(seed, Base64.NO_WRAP)).apply()
    }

    companion object {
        private const val KEY = "device_seed_b64"
    }
}
