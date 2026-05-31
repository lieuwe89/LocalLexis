#pragma once

#include <cstddef>
#include <cstdint>

namespace locallexis::net {

// Abstract source of body bytes for the streaming uploader. Implementations
// supply two passes over the same byte range: one to compute the SHA-256
// for signing, one to write the body to the socket.
//
// Pure C++ — no Arduino types — so host tests can drive it directly.
class BodySource {
public:
    virtual ~BodySource() = default;

    // Total byte count. Used for the Content-Length header.
    virtual size_t size() const = 0;

    // Reset the read cursor to the start of the body. Returns true on
    // success; on failure the caller aborts the upload attempt.
    virtual bool rewind() = 0;

    // Read up to ``max`` bytes into ``buf``. Returns the number of bytes
    // actually read; 0 at end-of-stream. Returning a value larger than
    // ``max`` is a programming error.
    virtual size_t readChunk(uint8_t* buf, size_t max) = 0;
};

}  // namespace locallexis::net
