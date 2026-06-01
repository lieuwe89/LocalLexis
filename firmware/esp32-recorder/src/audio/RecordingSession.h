#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>

#include "audio/WavSink.h"

namespace locallexis::audio {

enum class RecState { Standby, Recording, Stopping };
enum class StopReason { User, Full, Error };

class AudioCodec {
public:
    virtual ~AudioCodec() = default;
    virtual bool powerOnAndConfigure() = 0;
    virtual void powerOff() = 0;
};

class AudioCapture {
public:
    virtual ~AudioCapture() = default;
    virtual bool start() = 0;
    virtual void stop() = 0;
};

class Button {
public:
    virtual ~Button() = default;
    virtual void arm() = 0;
    virtual void disarm() = 0;
};

class SinkFactory {
public:
    virtual ~SinkFactory() = default;
    virtual bool sdReady() const = 0;
    virtual WavSink* makeSink(bool sd) = 0;  // non-owning; lifetime managed by caller
};

class RecordingSession {
public:
    using StateCallback = std::function<void(RecState, StopReason)>;
    using ClipCallback = std::function<void(WavSink&)>;

    RecordingSession(AudioCodec& codec, AudioCapture& capture, Button& button, SinkFactory& sinks);

    void setOnState(StateCallback cb) { onState_ = std::move(cb); }
    void setOnClip(ClipCallback cb) { onClip_ = std::move(cb); }

    void toggle();
    void onPcm(const uint8_t* bytes, size_t len);
    RecState state() const { return state_; }

private:
    void startRecording();
    void stopRecording(StopReason reason);
    void emitState(StopReason reason);

    AudioCodec& codec_;
    AudioCapture& capture_;
    Button& button_;
    SinkFactory& sinks_;
    WavSink* sink_ = nullptr;
    RecState state_ = RecState::Standby;
    StateCallback onState_;
    ClipCallback onClip_;
};

}  // namespace locallexis::audio
