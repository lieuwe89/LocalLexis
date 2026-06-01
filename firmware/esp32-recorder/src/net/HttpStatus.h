#pragma once

#include <string>

namespace locallexis::net {

// Extracts the numeric status from a response that begins with an HTTP status
// line ("HTTP/1.1 202 Accepted ..."). Returns 0 when no status line is present
// (e.g. a connection-error string).
int httpStatusFromResponse(const std::string& response);

}  // namespace locallexis::net
