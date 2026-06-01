#pragma once

#include <Arduino.h>
#include <functional>

#include <driver/i2s.h>
#include <freertos/FreeRTOS.h>
#include <freertos/ringbuf.h>
#include <freertos/task.h>

#include "audio/RecordingSession.h"  // AudioCapture

namespace locallexis::audio {

struct I2SPins {
    int mclk, bclk, ws, din;  // din = mic (ASDOUT). dout unused for mic.
};

class I2SCapture : public AudioCapture {
public:
    using PcmCallback = std::function<void(const uint8_t*, size_t)>;

    I2SCapture(const I2SPins& pins, uint32_t sampleRate);
    ~I2SCapture();

    void setPcmCallback(PcmCallback cb) { onPcm_ = std::move(cb); }

    bool start() override;  // install driver, spawn reader task
    void stop() override;   // stop task, uninstall driver
    void pump();            // drain ringbuffer on loopTask -> onPcm_

    uint32_t overrunCount() const { return overruns_; }

private:
    static void readerTaskThunk(void* arg);
    void readerLoop();

    I2SPins pins_;
    uint32_t sampleRate_;
    PcmCallback onPcm_;

    RingbufHandle_t ring_ = nullptr;
    TaskHandle_t task_ = nullptr;
    volatile bool running_ = false;
    volatile bool installed_ = false;
    volatile uint32_t overruns_ = 0;
};

}  // namespace locallexis::audio
