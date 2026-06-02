#include "audio/I2SCapture.h"

// Legacy ESP-IDF 4.4 I2S driver (driver/i2s.h): this build runs arduino-esp32
// 2.0.17, which predates the channel-based i2s_std API. Stereo 32-bit MSB in,
// left-channel high 16 bits out -> mono 16-bit (same ES8311 path).
namespace locallexis::audio {

namespace {
constexpr i2s_port_t kPort = I2S_NUM_0;
constexpr int kDmaBufCount = 6;
constexpr int kDmaBufLen = 256;                   // frames per DMA buffer
constexpr size_t kReadFrames = 256;               // frames per i2s read
constexpr size_t kRingBytes = 32 * 1024;          // mono16 ring capacity
constexpr size_t kPumpChunkBytes = 4096;
}  // namespace

I2SCapture::I2SCapture(const I2SPins& pins, uint32_t sampleRate)
    : pins_(pins), sampleRate_(sampleRate) {}

I2SCapture::~I2SCapture() { stop(); }

bool I2SCapture::start() {
    if (running_) return false;

    ring_ = xRingbufferCreate(kRingBytes, RINGBUF_TYPE_BYTEBUF);
    if (!ring_) return false;

    i2s_config_t cfg = {
        .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = sampleRate_,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,   // stereo
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,  // ES8311 SDP=00 is Philips I2S
                                                             // (1-BCLK delay); MSB here shifted
                                                             // data 1 bit -> unipolar garbage.
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = kDmaBufCount,
        .dma_buf_len = kDmaBufLen,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0,
        .mclk_multiple = I2S_MCLK_MULTIPLE_256,         // ESP supplies 256xfs MCLK
        .bits_per_chan = I2S_BITS_PER_CHAN_32BIT,
    };
    if (i2s_driver_install(kPort, &cfg, 0, nullptr) != ESP_OK) {
        vRingbufferDelete(ring_); ring_ = nullptr;
        return false;
    }

    i2s_pin_config_t pinCfg = {
        .mck_io_num = pins_.mclk,
        .bck_io_num = pins_.bclk,
        .ws_io_num = pins_.ws,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = pins_.din,
    };
    if (i2s_set_pin(kPort, &pinCfg) != ESP_OK) {
        i2s_driver_uninstall(kPort);
        vRingbufferDelete(ring_); ring_ = nullptr;
        return false;
    }

    installed_ = true;
    running_ = true;
    overruns_ = 0;
    xTaskCreatePinnedToCore(&I2SCapture::readerTaskThunk, "i2s_rx", 4096, this,
                            tskIDLE_PRIORITY + 5, &task_, 1);
    return true;
}

void I2SCapture::readerTaskThunk(void* arg) {
    static_cast<I2SCapture*>(arg)->readerLoop();
}

void I2SCapture::readerLoop() {
    // Stereo 32-bit frames in; emit mono 16-bit (left channel, high word).
    static int32_t in[kReadFrames * 2];
    static int16_t mono[kReadFrames];
    while (running_) {
        size_t got = 0;
        const esp_err_t err = i2s_read(kPort, in, sizeof(in), &got, pdMS_TO_TICKS(100));
        if (err != ESP_OK || got == 0) continue;
        const size_t frames = got / (sizeof(int32_t) * 2);
        for (size_t i = 0; i < frames; ++i) {
            mono[i] = static_cast<int16_t>(in[i * 2] >> 16);  // left, top 16 bits
        }
        if (xRingbufferSend(ring_, mono, frames * sizeof(int16_t), 0) != pdTRUE) {
            ++overruns_;  // ring full: drop this buffer, keep recording
        }
    }
    vTaskDelete(nullptr);
}

void I2SCapture::pump() {
    if (!ring_ || !onPcm_) return;
    for (;;) {
        size_t n = 0;
        void* item = xRingbufferReceiveUpTo(ring_, &n, 0, kPumpChunkBytes);
        if (!item) break;
        onPcm_(static_cast<const uint8_t*>(item), n);
        vRingbufferReturnItem(ring_, item);
    }
}

void I2SCapture::stop() {
    if (!running_) return;
    running_ = false;
    if (task_) {
        // readerLoop exits on running_==false then self-deletes; give it a tick.
        delay(150);
        task_ = nullptr;
    }
    if (installed_) {
        i2s_driver_uninstall(kPort);
        installed_ = false;
    }
    if (ring_) {
        vRingbufferDelete(ring_);
        ring_ = nullptr;
    }
}

}  // namespace locallexis::audio
