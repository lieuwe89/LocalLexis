package app.locallexis

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import app.locallexis.data.config.HubConfigStore
import app.locallexis.data.config.PrefsHubConfigStore
import app.locallexis.data.crypto.CryptoBox
import app.locallexis.data.crypto.EncryptedPrefsSecretStorage
import app.locallexis.data.crypto.EncryptedPrefsWorkspaceKeyStore
import app.locallexis.data.crypto.LazysodiumCryptoBox
import app.locallexis.data.crypto.SecretStorage
import app.locallexis.data.crypto.WorkspaceKeyStore
import app.locallexis.data.db.LocalLexisDatabase
import app.locallexis.data.pairing.DeviceIdentityStore
import app.locallexis.data.pairing.PairingClient
import app.locallexis.data.pairing.PairingPayloadV1
import app.locallexis.data.pairing.PairingResult
import app.locallexis.data.pairing.PrefsDeviceIdentityStore
import app.locallexis.data.pairing.SignedRequestInterceptor
import app.locallexis.data.sync.DefaultLibrarySync
import app.locallexis.data.sync.LibrarySync
import app.locallexis.data.sync.SyncClient
import app.locallexis.data.sync.SyncIngest
import app.locallexis.data.sync.UnpairedLibrarySync
import com.goterl.lazysodium.LazySodiumAndroid
import com.goterl.lazysodium.SodiumAndroid
import okhttp3.OkHttpClient

/**
 * Application-scoped dependency graph. Every member is lazy so the first
 * screen composition pays construction cost, not app start. One
 * EncryptedSharedPreferences file backs all four prefs-backed stores
 * (keys do not collide: workspace_key_b64 / device_id / device_seed_b64 /
 * hub_url + workspace_id).
 */
class AppGraph(context: Context) {

    private val appContext: Context = context.applicationContext

    private val securePrefs: SharedPreferences by lazy {
        val masterKey = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            SECURE_FILE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    val sodium: LazySodiumAndroid by lazy { LazySodiumAndroid(SodiumAndroid()) }
    val secretStorage: SecretStorage by lazy { EncryptedPrefsSecretStorage(securePrefs) }
    val cryptoBox: CryptoBox by lazy { LazysodiumCryptoBox(secretStorage, sodium) }
    val workspaceKeyStore: WorkspaceKeyStore by lazy { EncryptedPrefsWorkspaceKeyStore(securePrefs) }
    val deviceIdentityStore: DeviceIdentityStore by lazy { PrefsDeviceIdentityStore(securePrefs) }
    val hubConfig: HubConfigStore by lazy { PrefsHubConfigStore(securePrefs) }
    val db: LocalLexisDatabase by lazy { LocalLexisDatabase.get(appContext) }

    val okHttp: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .addInterceptor(SignedRequestInterceptor(cryptoBox, deviceIdentityStore))
            .build()
    }

    val pairingClient: PairingClient by lazy {
        PairingClient(cryptoBox, workspaceKeyStore, deviceIdentityStore, okHttp)
    }

    /**
     * Production pairing call. Persists hub_url + workspace_id on success
     * so the sync stack is constructible afterwards. Consumed by block
     * 8.3b (PairingViewModel); unused this block.
     */
    val pair: suspend (PairingPayloadV1, String) -> PairingResult = { payload, name ->
        pairingClient.exchange(payload, name).also { result ->
            hubConfig.put(hubUrl = payload.hubUrl, workspaceId = result.workspaceId)
        }
    }

    /** Real sync when paired, else a fallback that surfaces "not paired". */
    fun librarySync(): LibrarySync {
        val base = hubConfig.getHubUrl() ?: return UnpairedLibrarySync
        return DefaultLibrarySync(SyncClient(okHttp, base), SyncIngest(db))
    }

    fun workspaceId(): String = hubConfig.getWorkspaceId() ?: ""

    companion object {
        private const val SECURE_FILE = "locallexis_secure"
    }
}

/** Resolve the application graph from any Compose/Android [Context]. */
val Context.appGraph: AppGraph
    get() = (applicationContext as App).graph
