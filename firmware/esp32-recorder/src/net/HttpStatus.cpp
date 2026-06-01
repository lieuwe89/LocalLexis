#include "net/HttpStatus.h"

#include <cctype>
#include <cstdlib>

namespace locallexis::net {

int httpStatusFromResponse(const std::string& response) {
    if (response.rfind("HTTP/", 0) != 0) return 0;  // must start with the status line
    const size_t firstSpace = response.find(' ');
    if (firstSpace == std::string::npos) return 0;
    size_t i = firstSpace + 1;
    int code = 0;
    bool sawDigit = false;
    while (i < response.size() && std::isdigit(static_cast<unsigned char>(response[i]))) {
        code = code * 10 + (response[i] - '0');
        sawDigit = true;
        ++i;
    }
    return sawDigit ? code : 0;
}

}  // namespace locallexis::net
