#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

#include "ui/UiBitmaps.h"

using namespace locallexis::ui;

namespace {

bool bitSet(const std::vector<uint8_t>& bytes, int stride, int x, int y) {
    return (bytes[y * stride + (x >> 3)] >> (7 - (x & 7))) & 1;
}

void test_dimensions() {
    assert(btBitmap().w == 9 && btBitmap().h == 13);
    assert(fullBitmap().w == 13 && fullBitmap().h == 13);
    assert(micBitmap().w == 10 && micBitmap().h == 16);
}

void test_pack_bt_matches_rows() {
    const auto& s = btBitmap();
    const int stride = (s.w + 7) / 8;
    std::vector<uint8_t> bytes(stride * s.h, 0);
    assert(packBitmap(s, bytes.data(), bytes.size()) == bytes.size());
    // Every '#' in the source rows must be a set bit, every ' ' must be clear.
    for (int y = 0; y < s.h; ++y)
        for (int x = 0; x < s.w; ++x)
            assert(bitSet(bytes, stride, x, y) == (s.rows[y][x] == '#'));
}

void test_pack_rejects_small_buffer() {
    const auto& s = fullBitmap();
    uint8_t tiny[1];
    assert(packBitmap(s, tiny, sizeof(tiny)) == 0);
}

}  // namespace

int main() {
    test_dimensions();
    test_pack_bt_matches_rows();
    test_pack_rejects_small_buffer();
    std::cout << "test_ui_icons: OK" << std::endl;
    return 0;
}
