#include "audio/RecordingSession.h"

namespace locallexis::audio {

RecordingSession::RecordingSession(AudioCodec& codec, AudioCapture& capture,
                                   Button& button, SinkFactory& sinks)
    : codec_(codec), capture_(capture), button_(button), sinks_(sinks) {}

void RecordingSession::emitState(StopReason reason) {
    if (onState_) onState_(state_, reason);
}

void RecordingSession::toggle() {
    if (state_ == RecState::Standby) {
        startRecording();
    } else if (state_ == RecState::Recording) {
        stopRecording(StopReason::User);
    }
    // Stopping: ignored.
}

void RecordingSession::startRecording() {
    const bool sd = sinks_.sdReady();
    sink_ = sinks_.makeSink(sd);
    if (sink_ == nullptr || !sink_->open()) {
        sink_ = nullptr;
        state_ = RecState::Standby;
        emitState(StopReason::Error);
        return;
    }
    if (!codec_.powerOnAndConfigure()) {
        sink_->discard();
        sink_ = nullptr;
        state_ = RecState::Standby;
        emitState(StopReason::Error);
        return;
    }
    if (!capture_.start()) {
        codec_.powerOff();
        sink_->discard();
        sink_ = nullptr;
        state_ = RecState::Standby;
        emitState(StopReason::Error);
        return;
    }
    state_ = RecState::Recording;
    button_.arm();
    emitState(StopReason::User);
}

void RecordingSession::onPcm(const uint8_t* bytes, size_t len) {
    if (state_ != RecState::Recording || sink_ == nullptr) return;
    if (sink_->write(bytes, len)) return;
    // write refused: cap-hit if we are at/over capacity, else a real failure.
    if (sink_->bytesWritten() >= sink_->capacityBytes()) {
        stopRecording(StopReason::Full);
    } else {
        stopRecording(StopReason::Error);
    }
}

void RecordingSession::stopRecording(StopReason reason) {
    if (state_ != RecState::Recording) return;
    state_ = RecState::Stopping;
    button_.disarm();

    capture_.stop();
    codec_.powerOff();

    if (sink_ != nullptr) {
        if (sink_->close()) {
            if (onClip_) onClip_(*sink_);
        } else {
            sink_->discard();
        }
        sink_ = nullptr;
    }

    state_ = RecState::Standby;
    button_.arm();
    emitState(reason);
}

}  // namespace locallexis::audio
