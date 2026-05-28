package app.locallexis.data.config

import android.content.SharedPreferences

/**
 * Persists the hub coordinates learned at pairing time: the hub base URL
 * (used as SyncClient baseUrl) and the workspace id (used as
 * LibraryViewModel workspaceId). Production wiring co-locates them in the
 * same EncryptedSharedPreferences bag as the auth material.
 */
interface HubConfigStore {
    fun getHubUrl(): String?
    fun getWorkspaceId(): String?
    fun put(hubUrl: String, workspaceId: String)
    fun clear()
    fun isPaired(): Boolean
}

class PrefsHubConfigStore(private val prefs: SharedPreferences) : HubConfigStore {
    override fun getHubUrl(): String? = prefs.getString(KEY_HUB_URL, null)
    override fun getWorkspaceId(): String? = prefs.getString(KEY_WORKSPACE_ID, null)

    override fun put(hubUrl: String, workspaceId: String) {
        prefs.edit()
            .putString(KEY_HUB_URL, hubUrl)
            .putString(KEY_WORKSPACE_ID, workspaceId)
            .apply()
    }

    override fun clear() {
        prefs.edit().remove(KEY_HUB_URL).remove(KEY_WORKSPACE_ID).apply()
    }

    override fun isPaired(): Boolean = getHubUrl() != null && getWorkspaceId() != null

    companion object {
        const val KEY_HUB_URL = "hub_url"
        const val KEY_WORKSPACE_ID = "workspace_id"
    }
}

class InMemoryHubConfigStore : HubConfigStore {
    private var hubUrl: String? = null
    private var workspaceId: String? = null
    override fun getHubUrl(): String? = hubUrl
    override fun getWorkspaceId(): String? = workspaceId
    override fun put(hubUrl: String, workspaceId: String) {
        this.hubUrl = hubUrl
        this.workspaceId = workspaceId
    }
    override fun clear() {
        hubUrl = null
        workspaceId = null
    }
    override fun isPaired(): Boolean = hubUrl != null && workspaceId != null
}
