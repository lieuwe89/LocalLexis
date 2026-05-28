package app.locallexis.data.crypto

import com.goterl.lazysodium.LazySodiumJava
import com.goterl.lazysodium.SodiumJava
import com.goterl.lazysodium.interfaces.Box
import com.goterl.lazysodium.interfaces.Sign
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class CryptoBoxTest {

    private lateinit var sodium: LazySodiumJava
    private lateinit var storage: InMemorySecretStorage
    private lateinit var crypto: CryptoBox

    @Before
    fun setUp() {
        sodium = LazySodiumJava(SodiumJava())
        storage = InMemorySecretStorage()
        crypto = LazysodiumCryptoBox(storage, sodium)
    }

    @Test
    fun devicePublicKeyIsThirtyTwoBytes() {
        val pubkey = crypto.devicePublicKey()
        assertEquals(32, pubkey.size)
    }

    @Test
    fun devicePublicKeyIsIdempotent() {
        val first = crypto.devicePublicKey()
        val second = crypto.devicePublicKey()
        assertArrayEquals(first, second)
    }

    @Test
    fun cryptoBoxReusesPersistedSeed() {
        val pubkey1 = crypto.devicePublicKey()

        val crypto2 = LazysodiumCryptoBox(storage, sodium)
        val pubkey2 = crypto2.devicePublicKey()

        assertArrayEquals(pubkey1, pubkey2)
    }

    @Test
    fun signRequestVerifiesAgainstDevicePublicKey() {
        val pubkey = crypto.devicePublicKey()
        val body = """{"foo":"bar"}""".toByteArray()
        val sig = crypto.signRequest("POST", "/v1/relabel", body)

        assertEquals(Sign.BYTES, sig.size)
        val message = "POST".toByteArray() + "\n".toByteArray() +
            "/v1/relabel".toByteArray() + "\n".toByteArray() + body
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, pubkey)
        assertTrue("signature verification", ok)
    }

    @Test
    fun signRequestEmptyBody() {
        val pubkey = crypto.devicePublicKey()
        val sig = crypto.signRequest("GET", "/sync/snapshot", ByteArray(0))

        val message = "GET".toByteArray() + "\n".toByteArray() +
            "/sync/snapshot".toByteArray() + "\n".toByteArray()
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, pubkey)
        assertTrue(ok)
    }

    @Test
    fun openSealedBoxDecryptsPlaintext() {
        val devicePubkey = crypto.devicePublicKey()

        // Hub side: convert device Ed25519 pubkey → Curve25519 pubkey,
        // then sealedbox the workspace key.
        val curvePubkey = ByteArray(Box.PUBLICKEYBYTES)
        assertTrue(
            sodium.convertPublicKeyEd25519ToCurve25519(curvePubkey, devicePubkey)
        )

        val workspaceKey = "0123456789abcdef0123456789abcdef".toByteArray()
        val sealedLen = workspaceKey.size + Box.SEALBYTES
        val sealed = ByteArray(sealedLen)
        assertTrue(
            sodium.cryptoBoxSeal(sealed, workspaceKey, workspaceKey.size.toLong(), curvePubkey)
        )

        val opened = crypto.openSealedBox(sealed)
        assertArrayEquals(workspaceKey, opened)
    }

    @Test(expected = SealedBoxOpenException::class)
    fun openSealedBoxRejectsTamperedCiphertext() {
        val devicePubkey = crypto.devicePublicKey()
        val curvePubkey = ByteArray(Box.PUBLICKEYBYTES)
        sodium.convertPublicKeyEd25519ToCurve25519(curvePubkey, devicePubkey)

        val workspaceKey = ByteArray(32) { it.toByte() }
        val sealed = ByteArray(workspaceKey.size + Box.SEALBYTES)
        sodium.cryptoBoxSeal(sealed, workspaceKey, workspaceKey.size.toLong(), curvePubkey)
        // Flip a byte in the auth-protected region.
        sealed[sealed.size - 1] = (sealed[sealed.size - 1].toInt() xor 0xFF).toByte()

        crypto.openSealedBox(sealed)
    }

    @Test
    fun secretStorageStartsEmpty() {
        val fresh = InMemorySecretStorage()
        assertEquals(null, fresh.getSecretSeed())
    }

    @Test
    fun secretStorageRoundTrip() {
        val fresh = InMemorySecretStorage()
        val seed = ByteArray(32) { it.toByte() }
        fresh.putSecretSeed(seed)

        val got = fresh.getSecretSeed()
        assertNotNull(got)
        assertArrayEquals(seed, got)
        // Returned value is a copy, not aliased.
        got!![0] = 0xFF.toByte()
        assertArrayEquals(seed, fresh.getSecretSeed())
    }
}
