package app.locallexis.ui.settings

import app.locallexis.data.config.InMemoryHubConfigStore
import app.locallexis.data.pairing.DeviceIdentityStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    private class FakeDeviceIdentityStore(private var id: String?) : DeviceIdentityStore {
        override fun getDeviceId(): String? = id
        override fun putDeviceId(id: String) { this.id = id }
        override fun clear() { id = null }
    }

    @Before fun setUp() { Dispatchers.setMain(testDispatcher) }

    @After fun tearDown() { Dispatchers.resetMain() }

    private fun pairedConfig() = InMemoryHubConfigStore().apply {
        put("https://192.168.1.50:8443", "ws_a", "PIN==")
    }

    @Test fun snapshotReflectsPairedConfig() = runTest(testDispatcher) {
        val vm = SettingsViewModel(
            hubConfig = pairedConfig(),
            deviceIdentityStore = FakeDeviceIdentityStore("dev-1"),
            clearIdentity = {},
            runSync = {},
            scope = TestScope(testDispatcher),
        )
        val s = vm.state.value
        assertTrue(s.paired)
        assertEquals("https://192.168.1.50:8443", s.hubUrl)
        assertEquals("ws_a", s.workspaceId)
        assertTrue(s.tlsPinned)
        assertEquals("dev-1", s.deviceId)
    }

    @Test fun syncNowSuccess() = runTest(testDispatcher) {
        var called = false
        val vm = SettingsViewModel(
            hubConfig = pairedConfig(),
            deviceIdentityStore = FakeDeviceIdentityStore("dev-1"),
            clearIdentity = {},
            runSync = { called = true },
            scope = TestScope(testDispatcher),
        )
        vm.syncNow()
        advanceUntilIdle()
        assertTrue(called)
        assertEquals(SyncStatus.Success, vm.state.value.sync)
    }

    @Test fun syncNowFailureSurfacesMessage() = runTest(testDispatcher) {
        val vm = SettingsViewModel(
            hubConfig = pairedConfig(),
            deviceIdentityStore = FakeDeviceIdentityStore("dev-1"),
            clearIdentity = {},
            runSync = { throw RuntimeException("hub returned HTTP 503") },
            scope = TestScope(testDispatcher),
        )
        vm.syncNow()
        advanceUntilIdle()
        val sync = vm.state.value.sync
        assertTrue(sync is SyncStatus.Failed)
        assertEquals("hub returned HTTP 503", (sync as SyncStatus.Failed).message)
    }

    @Test fun syncNowWhenUnpairedIsNoOp() = runTest(testDispatcher) {
        var called = false
        val vm = SettingsViewModel(
            hubConfig = InMemoryHubConfigStore(),
            deviceIdentityStore = FakeDeviceIdentityStore(null),
            clearIdentity = {},
            runSync = { called = true },
            scope = TestScope(testDispatcher),
        )
        vm.syncNow()
        advanceUntilIdle()
        assertFalse(called)
        assertEquals(SyncStatus.Idle, vm.state.value.sync)
    }

    @Test fun unpairClearsIdentityAndUpdatesSnapshot() = runTest(testDispatcher) {
        val config = pairedConfig()
        val device = FakeDeviceIdentityStore("dev-1")
        val vm = SettingsViewModel(
            hubConfig = config,
            deviceIdentityStore = device,
            clearIdentity = { config.clear(); device.clear() },
            runSync = {},
            scope = TestScope(testDispatcher),
        )
        assertTrue(vm.state.value.paired)
        vm.unpair()
        val s = vm.state.value
        assertFalse(s.paired)
        assertEquals(null, s.hubUrl)
        assertEquals(null, s.deviceId)
    }
}
