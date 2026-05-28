package app.locallexis.data.crypto

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkspaceKeyStoreTest {

    @Test
    fun freshStoreReturnsNull() {
        val store: WorkspaceKeyStore = InMemoryWorkspaceKeyStore()
        assertNull(store.get())
    }

    @Test
    fun putAndGetRoundTrip() {
        val store: WorkspaceKeyStore = InMemoryWorkspaceKeyStore()
        val key = ByteArray(32) { it.toByte() }
        store.put(key)

        val got = store.get()
        assertArrayEquals(key, got)
    }

    @Test
    fun putOverwrites() {
        val store: WorkspaceKeyStore = InMemoryWorkspaceKeyStore()
        store.put(ByteArray(32) { 0x11 })
        val newKey = ByteArray(32) { 0x22 }
        store.put(newKey)
        assertArrayEquals(newKey, store.get())
    }

    @Test
    fun clearRemovesKey() {
        val store: WorkspaceKeyStore = InMemoryWorkspaceKeyStore()
        store.put(ByteArray(32) { 1 })
        store.clear()
        assertNull(store.get())
    }

    @Test
    fun getReturnsCopyNotAlias() {
        val store: WorkspaceKeyStore = InMemoryWorkspaceKeyStore()
        val original = ByteArray(32) { 0x33 }
        store.put(original)

        val got = store.get()!!
        got[0] = 0xFF.toByte()
        assertArrayEquals(original, store.get())
    }
}
