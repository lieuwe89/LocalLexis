package app.locallexis.data.crypto

import com.goterl.lazysodium.LazySodium
import com.goterl.lazysodium.interfaces.Box
import com.goterl.lazysodium.interfaces.Sign

/**
 * Device-side crypto primitives backing the hub pairing + signed-request
 * protocol. Public-key material exposed here is exactly what the hub
 * expects on the wire (raw Ed25519, 32 bytes). Secret material never
 * leaves the [SecretStorage] backend except briefly through libsodium.
 */
interface CryptoBox {

    /** Ed25519 verify key for this device, 32 raw bytes. Generates on first call. */
    fun devicePublicKey(): ByteArray

    /**
     * Detached Ed25519 signature over [method] + "\n" + [path] + "\n" + [body].
     * Matches the format that [speechtotext.api.auth.verify_device_signature]
     * checks on the hub.
     */
    fun signRequest(method: String, path: String, body: ByteArray): ByteArray

    /**
     * Open a sealedbox encrypted to this device's Ed25519 pubkey (after the
     * pubkey is converted to Curve25519). Mirrors PyNaCl's
     * `SealedBox(verify_key.to_curve25519_public_key()).encrypt(plaintext)`.
     */
    fun openSealedBox(ciphertext: ByteArray): ByteArray
}

/** Raised when the sealedbox MAC fails — auth failure or tampered ciphertext. */
class SealedBoxOpenException(message: String) : RuntimeException(message)

/**
 * Storage of the raw 32-byte Ed25519 seed. Implementations decide what
 * security layer (EncryptedSharedPreferences, file w/ Keystore-wrapped key,
 * test fake) backs the bytes.
 */
interface SecretStorage {
    fun getSecretSeed(): ByteArray?
    fun putSecretSeed(seed: ByteArray)
}

/** Non-persistent in-memory backend. For unit tests + ephemeral flows only. */
class InMemorySecretStorage : SecretStorage {
    @Volatile
    private var seed: ByteArray? = null

    override fun getSecretSeed(): ByteArray? = seed?.copyOf()

    override fun putSecretSeed(seed: ByteArray) {
        this.seed = seed.copyOf()
    }
}

/**
 * libsodium-backed [CryptoBox]. Caches the expanded Ed25519 keypair in
 * memory once derived from the seed; restart of the process re-derives
 * from the persisted seed in [storage].
 */
class LazysodiumCryptoBox(
    private val storage: SecretStorage,
    private val sodium: LazySodium,
) : CryptoBox {

    @Volatile
    private var keypair: KeyPair? = null

    override fun devicePublicKey(): ByteArray = ensureKeypair().publicKey.copyOf()

    override fun signRequest(method: String, path: String, body: ByteArray): ByteArray {
        val message = buildRequestMessage(method, path, body)
        val sig = ByteArray(Sign.BYTES)
        val ok = sodium.cryptoSignDetached(
            sig,
            message,
            message.size.toLong(),
            ensureKeypair().secretKey,
        )
        if (!ok) throw IllegalStateException("Ed25519 sign failed")
        return sig
    }

    override fun openSealedBox(ciphertext: ByteArray): ByteArray {
        val kp = ensureKeypair()
        val curveSecret = ByteArray(Box.SECRETKEYBYTES)
        val curvePublic = ByteArray(Box.PUBLICKEYBYTES)
        if (!sodium.convertSecretKeyEd25519ToCurve25519(curveSecret, kp.secretKey)) {
            throw IllegalStateException("Ed25519 → Curve25519 secret conversion failed")
        }
        if (!sodium.convertPublicKeyEd25519ToCurve25519(curvePublic, kp.publicKey)) {
            throw IllegalStateException("Ed25519 → Curve25519 public conversion failed")
        }

        if (ciphertext.size < Box.SEALBYTES) {
            throw SealedBoxOpenException(
                "ciphertext too short: ${ciphertext.size} < ${Box.SEALBYTES}",
            )
        }
        val plaintext = ByteArray(ciphertext.size - Box.SEALBYTES)
        val ok = sodium.cryptoBoxSealOpen(
            plaintext,
            ciphertext,
            ciphertext.size.toLong(),
            curvePublic,
            curveSecret,
        )
        if (!ok) throw SealedBoxOpenException("sealedbox MAC/decrypt failed")
        return plaintext
    }

    private fun ensureKeypair(): KeyPair {
        keypair?.let { return it }
        return synchronized(this) {
            keypair?.let { return it }
            val seed = storage.getSecretSeed() ?: run {
                val fresh = sodium.randomBytesBuf(Sign.SEEDBYTES)
                storage.putSecretSeed(fresh)
                fresh
            }
            val pk = ByteArray(Sign.PUBLICKEYBYTES)
            val sk = ByteArray(Sign.SECRETKEYBYTES)
            if (!sodium.cryptoSignSeedKeypair(pk, sk, seed)) {
                throw IllegalStateException("Ed25519 seed→keypair derivation failed")
            }
            KeyPair(pk, sk).also { keypair = it }
        }
    }

    private data class KeyPair(val publicKey: ByteArray, val secretKey: ByteArray)
}

internal fun buildRequestMessage(method: String, path: String, body: ByteArray): ByteArray {
    val prefix = method.toByteArray() + NEWLINE + path.toByteArray() + NEWLINE
    return prefix + body
}

private val NEWLINE = "\n".toByteArray()
