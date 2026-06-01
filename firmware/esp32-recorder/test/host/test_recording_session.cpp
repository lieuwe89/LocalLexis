#include <cassert>
#include <iostream>
#include <vector>

#include "audio/RecordingSession.h"
#include "audio/WavSink.h"

using namespace locallexis::audio;

namespace {

class FakeSink : public WavSink {
public:
    bool openOk = true;
    bool closeOk = true;
    size_t capacity = 1000;
    bool memory = false;

    bool open() override { opened = true; return openOk; }
    bool write(const uint8_t*, size_t len) override {
        if (written + len > capacity) { written = capacity; return false; }  // cap-hit
        if (failNextWrite) { failNextWrite = false; return false; }          // SD-style failure
        written += len;
        return true;
    }
    size_t bytesWritten() const override { return written; }
    size_t capacityBytes() const override { return capacity; }
    bool close() override { closed = true; return closeOk; }
    void discard() override { discarded = true; }
    bool isMemoryBacked() const override { return memory; }
    std::vector<uint8_t> takeBytes() override { return {1, 2, 3}; }

    bool opened = false, closed = false, discarded = false, failNextWrite = false;
    size_t written = 0;
};

class FakeCodec : public AudioCodec {
public:
    bool powerOk = true;
    bool powerOnAndConfigure() override { ++ons; return powerOk; }
    void powerOff() override { ++offs; }
    int ons = 0, offs = 0;
};

class FakeCapture : public AudioCapture {
public:
    bool startOk = true;
    bool start() override { ++starts; return startOk; }
    void stop() override { ++stops; }
    int starts = 0, stops = 0;
};

class FakeButton : public Button {
public:
    void arm() override { ++arms; }
    void disarm() override { ++disarms; }
    int arms = 0, disarms = 0;
};

class FakeFactory : public SinkFactory {
public:
    bool sd = true;
    FakeSink* fileSink;
    FakeSink* memSink;
    bool sdReady() const override { return sd; }
    WavSink* makeSink(bool useSd) override {
        choseSd = useSd;
        ++made;
        return useSd ? fileSink : memSink;
    }
    bool choseSd = false;
    int made = 0;
};

struct Harness {
    FakeSink file, mem;
    FakeCodec codec;
    FakeCapture capture;
    FakeButton button;
    FakeFactory factory;
    std::vector<StopReason> stateEvents;
    std::vector<RecState> stateStates;
    int clips = 0;
    bool lastClipMemory = false;

    RecordingSession session;

    Harness() : session(codec, capture, button, factory) {
        mem.memory = true;
        factory.fileSink = &file;
        factory.memSink = &mem;
        session.setOnState([this](RecState s, StopReason r) {
            stateStates.push_back(s);
            stateEvents.push_back(r);
        });
        session.setOnClip([this](WavSink& s) {
            ++clips;
            lastClipMemory = s.isMemoryBacked();
        });
    }
};

void test_basic_cycle() {
    Harness h;
    h.session.toggle();  // start
    assert(h.session.state() == RecState::Recording);
    assert(h.file.opened);
    assert(h.codec.ons == 1);
    assert(h.capture.starts == 1);
    assert(h.button.arms == 1);

    h.session.toggle();  // stop
    assert(h.session.state() == RecState::Standby);
    assert(h.capture.stops == 1);
    assert(h.codec.offs == 1);
    assert(h.file.closed);
    assert(h.clips == 1);
    assert(h.stateEvents.back() == StopReason::User);
}

void test_cap_hit_emits_full() {
    Harness h;
    h.file.capacity = 100;
    h.session.toggle();
    std::vector<uint8_t> chunk(200, 0);
    h.session.onPcm(chunk.data(), chunk.size());  // exceeds capacity
    assert(h.session.state() == RecState::Standby);
    assert(h.file.closed);
    assert(h.clips == 1);
    assert(h.stateEvents.back() == StopReason::Full);
}

void test_sd_write_failure_emits_error() {
    Harness h;
    h.file.capacity = 100000;
    h.session.toggle();
    h.file.failNextWrite = true;
    std::vector<uint8_t> chunk(10, 0);
    h.session.onPcm(chunk.data(), chunk.size());  // write fails, not at cap
    assert(h.session.state() == RecState::Standby);
    assert(h.stateEvents.back() == StopReason::Error);
}

void test_tap_during_stopping_ignored() {
    // onPcm that triggers a stop transitions through Stopping internally; after it
    // returns we are Standby. Verify a second onPcm in Standby does nothing bad and
    // that exactly one clip was produced.
    Harness h;
    h.file.capacity = 50;
    h.session.toggle();
    std::vector<uint8_t> chunk(100, 0);
    h.session.onPcm(chunk.data(), chunk.size());  // cap-hit -> stop
    assert(h.session.state() == RecState::Standby);
    h.session.onPcm(chunk.data(), chunk.size());  // ignored in Standby
    assert(h.clips == 1);
}

void test_sink_open_fails_returns_to_standby() {
    Harness h;
    h.file.openOk = false;
    h.session.toggle();
    assert(h.session.state() == RecState::Standby);
    assert(h.codec.ons == 0);          // codec never powered
    assert(h.capture.starts == 0);
    assert(h.stateEvents.back() == StopReason::Error);
}

void test_codec_init_fails_discards_sink() {
    Harness h;
    h.codec.powerOk = false;
    h.session.toggle();
    assert(h.session.state() == RecState::Standby);
    assert(h.file.opened);
    assert(h.file.discarded);          // sink closed/discarded
    assert(h.capture.starts == 0);
    assert(h.stateEvents.back() == StopReason::Error);
}

void test_sd_present_picks_file_sink() {
    Harness h;
    h.factory.sd = true;
    h.session.toggle();
    assert(h.factory.choseSd == true);
    assert(h.file.opened);
}

void test_sd_absent_picks_memory_sink() {
    Harness h;
    h.factory.sd = false;
    h.session.toggle();
    assert(h.factory.choseSd == false);
    assert(h.mem.opened);
    h.session.toggle();                // stop
    assert(h.clips == 1);
    assert(h.lastClipMemory == true);  // memory clip delivered
}

}  // namespace

int main() {
    test_basic_cycle();
    test_cap_hit_emits_full();
    test_sd_write_failure_emits_error();
    test_tap_during_stopping_ignored();
    test_sink_open_fails_returns_to_standby();
    test_codec_init_fails_discards_sink();
    test_sd_present_picks_file_sink();
    test_sd_absent_picks_memory_sink();
    std::cout << "test_recording_session: OK" << std::endl;
    return 0;
}
