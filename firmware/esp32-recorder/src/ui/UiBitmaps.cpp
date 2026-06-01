#include "ui/UiBitmaps.h"

namespace locallexis::ui {

const char* const kBtRows[13] = {
    "...#.....", "...##....", "...#.#...", "#..#..#..", ".#.#.#...",
    "..###....", "...#.....", "..###....", ".#.#.#...", "#..#..#..",
    "...#.#...", "...##....", "...#.....",
};
const char* const kFullRows[13] = {
    "...########..", "..#......##..", ".#.......#...", "#........#...",
    "#.#.#.#..#...", "#.#.#.#..#...", "#.#.#.#..#...", "#........#...",
    "#........#...", "#........#...", "#........#...", "#........#...",
    ".########....",
};
const char* const kMicRows[16] = {
    "...####...", "..#....#..", "..#....#..", "..#.##.#..", "..#....#..",
    "..#....#..", "..#....#..", "...#..#...", "#..####..#", "#...##...#",
    ".#..##..#.", "..#.##.#..", "...####...", "....##....", "...####...",
    "..######..",
};

const BitmapSrc& btBitmap()   { static const BitmapSrc s{kBtRows, 9, 13};   return s; }
const BitmapSrc& fullBitmap() { static const BitmapSrc s{kFullRows, 13, 13}; return s; }
const BitmapSrc& micBitmap()  { static const BitmapSrc s{kMicRows, 10, 16};  return s; }

size_t packBitmap(const BitmapSrc& src, uint8_t* out, size_t outCap) {
    const size_t stride = (src.w + 7) / 8;
    const size_t need = stride * src.h;
    if (outCap < need) return 0;
    for (size_t i = 0; i < need; ++i) out[i] = 0;
    for (int y = 0; y < src.h; ++y) {
        const char* row = src.rows[y];
        for (int x = 0; x < src.w; ++x) {
            if (row[x] == '#') out[y * stride + (x >> 3)] |= (0x80 >> (x & 7));
        }
    }
    return need;
}

}  // namespace locallexis::ui
