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
import app.locallexis.data.http.HubTls
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
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
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

    // Pair-only OkHttp: the pairing token at /pair is single-use server-side,
    // so an OkHttp retry of the same POST burns the spent token and the second
    // attempt comes back 401 even when the first paired successfully. Disable
    // connection-failure retry on the pair client so a transient TLS or socket
    // hiccup surfaces as a normal user-visible error instead of a duplicate
    // POST. Sync and upload paths keep the default retry behaviour via
    // [okHttp] — those endpoints are not single-use.
    val pairingHttpClient: OkHttpClient by lazy {
        okHttp.newBuilder()
            .retryOnConnectionFailure(false)
            .build()
    }

    val pairingClient: PairingClient by lazy {
        PairingClient(cryptoBox, workspaceKeyStore, deviceIdentityStore, pairingHttpClient)
    }

    // Emits after each successful pairing exchange so screens with cached
    // post-sync state (e.g. LibraryViewModel's lastError) can react instead
    // of waiting for an app restart. Replay-1 so a subscriber that comes back
    // (tab switch via NavHost saveState/restoreState) still sees the most
    // recent pair event.
    private val _pairingEvents = MutableSharedFlow<Unit>(
        replay = 1,
        extraBufferCapacity = 1,
    )
    val pairingEvents: SharedFlow<Unit> = _pairingEvents.asSharedFlow()

    /**
     * Production pairing call. Persists hub_url + workspace_id on success
     * so the sync stack is constructible afterwards. Consumed by
     * PairingViewModel.
     */
    val pair: suspend (PairingPayloadV1, String) -> PairingResult = { payload, name ->
        val previousHubUrl = hubConfig.getHubUrl()
        val previousWorkspaceId = hubConfig.getWorkspaceId()
        val result = pairingClient.exchange(payload, name)
        // When the new hub differs from the previously paired one, drop any
        // persisted sync cursors so the next sync bootstraps fresh. Without
        // this, an /sync/since/<old-cursor> request against the new hub can
        // either 404 or return data the local DB then mixes with the
        // previous workspace's transcripts. Workspace_id is PK on
        // sync_state so unrelated workspaces are independent, but test
        // hubs sometimes reuse ids and production hub-swaps still benefit
        // from the wipe.
        val hubChanged = previousHubUrl != null &&
            (previousHubUrl != payload.hubUrl || previousWorkspaceId != result.workspaceId)
        if (hubChanged) {
            db.syncStateDao().deleteAll()
        }
        hubConfig.put(
            hubUrl = payload.hubUrl,
            workspaceId = result.workspaceId,
            tlsSpkiB64 = payload.tlsSpkiB64,
        )
        _pairingEvents.tryEmit(Unit)
        result
    }

    /** Real sync when paired, else a fallback that surfaces "not paired". */
    fun librarySync(): LibrarySync {
        val base = hubConfig.getHubUrl() ?: return UnpairedLibrarySync
        val client = HubTls.pinnedClient(okHttp, base, hubConfig.getTlsSpkiB64())
        return DefaultLibrarySync(SyncClient(client, base), SyncIngest(db))
    }

    fun workspaceId(): String = hubConfig.getWorkspaceId() ?: ""

    /** Wipe all pairing state: hub coordinates, workspace key W, device id. */
    fun unpair() {
        hubConfig.clear()
        workspaceKeyStore.clear()
        deviceIdentityStore.clear()
    }

    companion object {
        private const val SECURE_FILE = "locallexis_secure"
    }
}

/** Resolve the application graph from any Compose/Android [Context]. */
val Context.appGraph: AppGraph
    get() = (applicationContext as App).graph
