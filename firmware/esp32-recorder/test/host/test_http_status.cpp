#include <cassert>
#include <iostream>
#include <string>

#include "net/HttpStatus.h"

using locallexis::net::httpStatusFromResponse;

int main() {
    assert(httpStatusFromResponse("HTTP/1.1 202 Accepted\r\n{\"id\":1}") == 202);
    assert(httpStatusFromResponse("HTTP/1.1 400 Bad Request") == 400);
    assert(httpStatusFromResponse("HTTP/1.0 404 Not Found\r\nbody") == 404);
    assert(httpStatusFromResponse("HTTP/1.1 500 Internal Server Error") == 500);
    // No status line (network error string the uploader sets on failure):
    assert(httpStatusFromResponse("failed to connect to HTTP hub") == 0);
    assert(httpStatusFromResponse("") == 0);
    // Malformed (no code after the first space):
    assert(httpStatusFromResponse("HTTP/1.1") == 0);
    std::cout << "test_http_status: OK" << std::endl;
    return 0;
}
