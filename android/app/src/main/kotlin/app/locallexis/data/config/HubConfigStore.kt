package app.locallexis.data.config

import android.content.SharedPreferences

/**
 * Persists the hub coordinates learned at pairing time: the hub base URL
 * (used as SyncClient baseUrl), the workspace id (used as
 * LibraryViewModel workspaceId), and the hub's TLS SPKI pin when the hub
 * serves HTTPS (base64 of SHA-256 over the cert SubjectPublicKeyInfo, the
 * OkHttp CertificatePinner body — see speechtotext.api.tls). Production
 * wiring co-locates them in the same EncryptedSharedPreferences bag as the
 * auth material. The SPKI is null for plain-http LAN hubs.
 */
interface HubConfigStore {
    fun getHubUrl(): String?
    fun getWorkspaceId(): String?
    fun getTlsSpkiB64(): String?
    fun put(hubUrl: String, workspaceId: String, tlsSpkiB64: String? = null)
    fun clear()
    fun isPaired(): Boolean
}

class PrefsHubConfigStore(private val prefs: SharedPreferences) : HubConfigStore {
    override fun getHubUrl(): String? = prefs.getString(KEY_HUB_URL, null)
    override fun getWorkspaceId(): String? = prefs.getString(KEY_WORKSPACE_ID, null)
    override fun getTlsSpkiB64(): String? = prefs.getString(KEY_TLS_SPKI_B64, null)

    override fun put(hubUrl: String, workspaceId: String, tlsSpkiB64: String?) {
        prefs.edit()
            .putString(KEY_HUB_URL, hubUrl)
            .putString(KEY_WORKSPACE_ID, workspaceId)
            .apply {
                if (tlsSpkiB64 != null) putString(KEY_TLS_SPKI_B64, tlsSpkiB64)
                else remove(KEY_TLS_SPKI_B64)
            }
            .apply()
    }

    override fun clear() {
        prefs.edit()
            .remove(KEY_HUB_URL)
            .remove(KEY_WORKSPACE_ID)
            .remove(KEY_TLS_SPKI_B64)
            .apply()
    }

    override fun isPaired(): Boolean = getHubUrl() != null && getWorkspaceId() != null

    companion object {
        const val KEY_HUB_URL = "hub_url"
        const val KEY_WORKSPACE_ID = "workspace_id"
        const val KEY_TLS_SPKI_B64 = "tls_spki_b64"
    }
}

class InMemoryHubConfigStore : HubConfigStore {
    private var hubUrl: String? = null
    private var workspaceId: String? = null
    private var tlsSpkiB64: String? = null
    override fun getHubUrl(): String? = hubUrl
    override fun getWorkspaceId(): String? = workspaceId
    override fun getTlsSpkiB64(): String? = tlsSpkiB64
    override fun put(hubUrl: String, workspaceId: String, tlsSpkiB64: String?) {
        this.hubUrl = hubUrl
        this.workspaceId = workspaceId
        this.tlsSpkiB64 = tlsSpkiB64
    }
    override fun clear() {
        hubUrl = null
        workspaceId = null
        tlsSpkiB64 = null
    }
    override fun isPaired(): Boolean = hubUrl != null && workspaceId != null
}
