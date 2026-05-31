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
        val sig = crypto.signRequest(
            method = "POST",
            path = "/v1/relabel",
            query = "",
            timestamp = "1716200000",
            nonce = "abc123",
            body = body,
        )

        assertEquals(Sign.BYTES, sig.size)
        val nl = byteArrayOf(0x0A)
        val bodyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(body)
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "POST".toByteArray() + nl +
            "/v1/relabel".toByteArray() + nl +
            "1716200000".toByteArray() + nl +
            "abc123".toByteArray() + nl +
            bodyDigest
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, pubkey)
        assertTrue("v2 signature verification", ok)
    }

    @Test
    fun signRequestEmptyBody() {
        val pubkey = crypto.devicePublicKey()
        val sig = crypto.signRequest(
            method = "GET",
            path = "/sync/snapshot",
            query = "limit=2",
            timestamp = "1716200001",
            nonce = "def456",
            body = ByteArray(0),
        )

        val nl = byteArrayOf(0x0A)
        val emptyDigest = java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(0))
        val message = "locallexis-sig-v2".toByteArray() + nl +
            "GET".toByteArray() + nl +
            "/sync/snapshot?limit=2".toByteArray() + nl +
            "1716200001".toByteArray() + nl +
            "def456".toByteArray() + nl +
            emptyDigest
        val ok = sodium.cryptoSignVerifyDetached(sig, message, message.size, pubkey)
        assertTrue(ok)
    }

    @Test
    fun signRequestMatchesCrossLanguageGoldenVector() {
        // Same vector as the hub's test_auth_v2.py and the firmware's
        // test_sign_v2.cpp. Three implementations must agree byte-for-byte.
        val goldenSeed = ByteArray(32) { it.toByte() }
        val sodium = LazySodiumJava(SodiumJava())
        val pk = ByteArray(Sign.PUBLICKEYBYTES)
        val sk = ByteArray(Sign.SECRETKEYBYTES)
        assertTrue(sodium.cryptoSignSeedKeypair(pk, sk, goldenSeed))

        val storage = InMemorySecretStorage().apply { putSecretSeed(goldenSeed) }
        val box = LazysodiumCryptoBox(storage, sodium)

        val sig = box.signRequest(
            method = "POST",
            path = "/jobs/upload",
            query = "filename=t.wav",
            timestamp = "1700000000",
            nonce = "abc123",
            body = "hello".toByteArray(),
        )
        val sigB64 = java.util.Base64.getEncoder().encodeToString(sig)
        assertEquals(
            "/OsfsMPLhgXoE+9izzKmxXq2JNcuGhUu6FbF23WnPYfqJQieQrYMTc8AbDa+g5j/" +
                "WonMiJpvQpspFU8DbgpZAw==",
            sigB64,
        )
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
