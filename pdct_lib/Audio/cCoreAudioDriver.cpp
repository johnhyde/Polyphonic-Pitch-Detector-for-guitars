
/*
 * File:   cCoreAudioDriver.cpp
 *
 * macOS CoreAudio AUHAL driver implementation.
 *
 * Design
 * ------
 * A single kAudioUnitSubType_HALOutput AudioUnit is created with both
 * input (bus 1) and output (bus 0) enabled on the default input device.
 * Using the same device for I/O is the norm for external audio
 * interfaces (which provide both capture and playback).
 *
 * The render callback (invoked by CoreAudio when output data is needed)
 * first pulls captured audio from bus 1 via AudioUnitRender, converts
 * from CoreAudio's non-interleaved float32 layout to the app's
 * interleaved cFloat (double) layout, calls m_process->process(), then
 * writes the resulting interleaved output back to the non-interleaved
 * CoreAudio output buffers.
 *
 * Sample rate
 * -----------
 * The driver queries the device's current nominal sample rate rather
 * than forcing 44.1 kHz.  If the device is already running at 44.1 or
 * 48 kHz the algorithm works correctly (SAMPLE_RATE in common_type.h
 * controls the resonator tuning; if they differ, pitch accuracy is
 * reduced but the app is still functional for testing).
 */

#ifdef __APPLE__

#include "cCoreAudioDriver.h"
#include "log_info.h"

#include <cstring>
#include <cstdlib>

/* kAudioObjectPropertyElementMain was kAudioObjectPropertyElementMaster
 * (value 0) before macOS 12 SDK.  Define the old name when the new one
 * is not available so the code compiles on older SDKs too.            */
#ifndef kAudioObjectPropertyElementMain
#define kAudioObjectPropertyElementMain 0
#endif

/* ------------------------------------------------------------------ */
/* Static render callback — forwards to the driver instance.          */
/* ------------------------------------------------------------------ */

static OSStatus sRenderCallback(void*                       inRefCon,
                                 AudioUnitRenderActionFlags* ioActionFlags,
                                 const AudioTimeStamp*        inTimeStamp,
                                 UInt32                        inBusNumber,
                                 UInt32                        inNumberFrames,
                                 AudioBufferList*              ioData)
{
    cCoreAudioDriver* driver = static_cast<cCoreAudioDriver*>(inRefCon);
    return driver->onRender(ioActionFlags, inTimeStamp,
                            inBusNumber, inNumberFrames, ioData);
}

/* ------------------------------------------------------------------ */
/* Constructor / Destructor                                            */
/* ------------------------------------------------------------------ */

cCoreAudioDriver::cCoreAudioDriver()
    : m_audioUnit(nullptr)
    , m_process(nullptr)
    , m_bufferSize(512)
    , m_numChannels(2)
    , m_inputBuffer(nullptr)
    , m_outputBuffer(nullptr)
    , m_inputBufferList(nullptr)
{
}

cCoreAudioDriver::~cCoreAudioDriver()
{
    close();
}

/* ------------------------------------------------------------------ */
/* open()                                                              */
/* ------------------------------------------------------------------ */

int cCoreAudioDriver::open(cString name)
{
    OSStatus err;

    /* --- 1. Find and instantiate the AUHAL component --- */

    AudioComponentDescription desc;
    memset(&desc, 0, sizeof(desc));
    desc.componentType         = kAudioUnitType_Output;
    desc.componentSubType      = kAudioUnitSubType_HALOutput;
    desc.componentManufacturer = kAudioUnitManufacturer_Apple;

    AudioComponent comp = AudioComponentFindNext(nullptr, &desc);
    if (!comp) {
        LOG_ERRO("CoreAudio: AudioComponentFindNext failed (no AUHAL)");
        return -1;
    }

    err = AudioComponentInstanceNew(comp, &m_audioUnit);
    if (err != noErr) {
        LOG_ERRO("CoreAudio: AudioComponentInstanceNew failed (%d)", (int)err);
        return -1;
    }

    /* --- 2. Enable output on bus 0 and input on bus 1 --- */

    UInt32 enable = 1;
    UInt32 disable = 0;

    err = AudioUnitSetProperty(m_audioUnit,
                               kAudioOutputUnitProperty_EnableIO,
                               kAudioUnitScope_Output, 0,
                               &enable, sizeof(enable));
    if (err != noErr) {
        LOG_ERRO("CoreAudio: failed to enable output bus (%d)", (int)err);
        return -1;
    }

    err = AudioUnitSetProperty(m_audioUnit,
                               kAudioOutputUnitProperty_EnableIO,
                               kAudioUnitScope_Input, 1,
                               &enable, sizeof(enable));
    if (err != noErr) {
        LOG_ERRO("CoreAudio: failed to enable input bus (%d)", (int)err);
        return -1;
    }

    /* Silence compiler warning — disable variable used only in the
     * block above on some SDK versions.                               */
    (void)disable;

    /* --- 3. Select the default input device for the AUHAL --- */

    AudioDeviceID inputDevice = kAudioObjectUnknown;
    UInt32 propSize = sizeof(inputDevice);

    AudioObjectPropertyAddress propAddr;
    propAddr.mSelector = kAudioHardwarePropertyDefaultInputDevice;
    propAddr.mScope    = kAudioObjectPropertyScopeGlobal;
    propAddr.mElement  = kAudioObjectPropertyElementMain;

    err = AudioObjectGetPropertyData(kAudioObjectSystemObject,
                                     &propAddr, 0, nullptr,
                                     &propSize, &inputDevice);
    if (err != noErr || inputDevice == kAudioObjectUnknown) {
        LOG_ERRO("CoreAudio: cannot get default input device (%d)", (int)err);
        return -1;
    }

    err = AudioUnitSetProperty(m_audioUnit,
                               kAudioOutputUnitProperty_CurrentDevice,
                               kAudioUnitScope_Global, 0,
                               &inputDevice, sizeof(inputDevice));
    if (err != noErr) {
        LOG_ERRO("CoreAudio: cannot set current device (%d)", (int)err);
        return -1;
    }

    /* --- 4. Query device sample rate and buffer frame size --- */

    Float64 deviceSampleRate = SAMPLE_RATE;
    propSize = sizeof(deviceSampleRate);

    AudioObjectPropertyAddress srAddr;
    srAddr.mSelector = kAudioDevicePropertyNominalSampleRate;
    srAddr.mScope    = kAudioObjectPropertyScopeGlobal;
    srAddr.mElement  = kAudioObjectPropertyElementMain;

    AudioObjectGetPropertyData(inputDevice, &srAddr,
                               0, nullptr, &propSize, &deviceSampleRate);

    UInt32 bufferFrameSize = 512;
    propSize = sizeof(bufferFrameSize);

    AudioObjectPropertyAddress bsAddr;
    bsAddr.mSelector = kAudioDevicePropertyBufferFrameSize;
    bsAddr.mScope    = kAudioObjectPropertyScopeGlobal;
    bsAddr.mElement  = kAudioObjectPropertyElementMain;

    AudioObjectGetPropertyData(inputDevice, &bsAddr,
                               0, nullptr, &propSize, &bufferFrameSize);

    m_bufferSize = (int)bufferFrameSize;
    if (m_bufferSize < 64) m_bufferSize = 64;

    /* --- 5. Set stream format (non-interleaved float32, stereo) --- */

    /*
     * Scope naming in AUHAL is counter-intuitive:
     *   bus 0  kAudioUnitScope_Input  = format the render callback delivers
     *                                   TO the output hardware
     *   bus 1  kAudioUnitScope_Output = format the input hardware delivers
     *                                   TO AudioUnitRender callers
     */
    AudioStreamBasicDescription fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.mSampleRate       = deviceSampleRate;
    fmt.mFormatID         = kAudioFormatLinearPCM;
    fmt.mFormatFlags      = kAudioFormatFlagsNativeFloatPacked
                          | kAudioFormatFlagIsNonInterleaved;
    fmt.mBitsPerChannel   = 32;
    fmt.mChannelsPerFrame = (UInt32)m_numChannels;
    fmt.mFramesPerPacket  = 1;
    fmt.mBytesPerFrame    = sizeof(float);
    fmt.mBytesPerPacket   = sizeof(float);

    /* Output format (what we push to speakers/interface output) */
    AudioUnitSetProperty(m_audioUnit,
                         kAudioUnitProperty_StreamFormat,
                         kAudioUnitScope_Input, 0,
                         &fmt, sizeof(fmt));

    /* Input format (what we receive from microphone/interface input) */
    AudioUnitSetProperty(m_audioUnit,
                         kAudioUnitProperty_StreamFormat,
                         kAudioUnitScope_Output, 1,
                         &fmt, sizeof(fmt));

    /* --- 6. Allocate interleaved processing buffers --- */

    m_inputBuffer  = new cFloat[m_bufferSize * m_numChannels];
    m_outputBuffer = new cFloat[m_bufferSize * m_numChannels];

    memset(m_inputBuffer,  0, m_bufferSize * m_numChannels * sizeof(cFloat));
    memset(m_outputBuffer, 0, m_bufferSize * m_numChannels * sizeof(cFloat));

    /* AudioBufferList for pulling non-interleaved input via
     * AudioUnitRender.  Each buffer holds one channel.               */
    size_t ablSize = sizeof(AudioBufferList)
                   + ((size_t)(m_numChannels - 1)) * sizeof(AudioBuffer);
    m_inputBufferList = static_cast<AudioBufferList*>(malloc(ablSize));
    if (!m_inputBufferList) {
        LOG_ERRO("CoreAudio: malloc AudioBufferList failed");
        return -1;
    }
    m_inputBufferList->mNumberBuffers = (UInt32)m_numChannels;
    for (int c = 0; c < m_numChannels; c++) {
        m_inputBufferList->mBuffers[c].mNumberChannels = 1;
        m_inputBufferList->mBuffers[c].mDataByteSize   =
            (UInt32)(m_bufferSize * sizeof(float));
        m_inputBufferList->mBuffers[c].mData =
            new float[m_bufferSize];
        memset(m_inputBufferList->mBuffers[c].mData, 0,
               m_bufferSize * sizeof(float));
    }

    /* --- 7. Register the output render callback --- */

    AURenderCallbackStruct cb;
    cb.inputProc       = sRenderCallback;
    cb.inputProcRefCon = this;

    err = AudioUnitSetProperty(m_audioUnit,
                               kAudioUnitProperty_SetRenderCallback,
                               kAudioUnitScope_Input, 0,
                               &cb, sizeof(cb));
    if (err != noErr) {
        LOG_ERRO("CoreAudio: failed to set render callback (%d)", (int)err);
        return -1;
    }

    /* --- 8. Initialize and start the AudioUnit --- */

    err = AudioUnitInitialize(m_audioUnit);
    if (err != noErr) {
        LOG_ERRO("CoreAudio: AudioUnitInitialize failed (%d)", (int)err);
        return -1;
    }

    err = AudioOutputUnitStart(m_audioUnit);
    if (err != noErr) {
        LOG_ERRO("CoreAudio: AudioOutputUnitStart failed (%d)", (int)err);
        return -1;
    }

    LOG_INFO("CoreAudio: started — device %u, %.0f Hz, %d frames/buf, %d ch",
             (unsigned)inputDevice, deviceSampleRate,
             m_bufferSize, m_numChannels);
    return 0;
}

/* ------------------------------------------------------------------ */
/* close()                                                             */
/* ------------------------------------------------------------------ */

int cCoreAudioDriver::close()
{
    if (m_audioUnit) {
        AudioOutputUnitStop(m_audioUnit);
        AudioUnitUninitialize(m_audioUnit);
        AudioComponentInstanceDispose(m_audioUnit);
        m_audioUnit = nullptr;
    }

    delete[] m_inputBuffer;
    m_inputBuffer = nullptr;

    delete[] m_outputBuffer;
    m_outputBuffer = nullptr;

    if (m_inputBufferList) {
        for (UInt32 i = 0; i < m_inputBufferList->mNumberBuffers; i++) {
            delete[] static_cast<float*>(m_inputBufferList->mBuffers[i].mData);
        }
        free(m_inputBufferList);
        m_inputBufferList = nullptr;
    }

    return 0;
}

/* ------------------------------------------------------------------ */
/* attachProcess()                                                     */
/* ------------------------------------------------------------------ */

void cCoreAudioDriver::attachProcess(cJackProcess* process)
{
    m_process = process;
}

/* ------------------------------------------------------------------ */
/* onRender() — called on CoreAudio's real-time thread                */
/* ------------------------------------------------------------------ */

OSStatus cCoreAudioDriver::onRender(AudioUnitRenderActionFlags* ioActionFlags,
                                     const AudioTimeStamp*        inTimeStamp,
                                     UInt32                        /*inOutputBusNumber*/,
                                     UInt32                        inNumberFrames,
                                     AudioBufferList*              ioData)
{
    /* Clamp to pre-allocated buffer size. */
    if ((int)inNumberFrames > m_bufferSize)
        inNumberFrames = (UInt32)m_bufferSize;

    /* Reset byte sizes before each AudioUnitRender call (required). */
    for (UInt32 c = 0; c < m_inputBufferList->mNumberBuffers; c++) {
        m_inputBufferList->mBuffers[c].mDataByteSize =
            inNumberFrames * sizeof(float);
    }

    /* Pull captured audio from the input bus (bus 1). */
    OSStatus err = AudioUnitRender(m_audioUnit,
                                   ioActionFlags,
                                   inTimeStamp,
                                   1,               /* input bus */
                                   inNumberFrames,
                                   m_inputBufferList);
    if (err != noErr) {
        /* On error, silence the output and return without crashing. */
        for (UInt32 b = 0; b < ioData->mNumberBuffers; b++) {
            memset(ioData->mBuffers[b].mData, 0,
                   ioData->mBuffers[b].mDataByteSize);
        }
        return noErr;
    }

    /* Convert non-interleaved float32 (CoreAudio) →
     * interleaved cFloat (double) expected by cJackProcess::process(). */
    int nch = (int)m_inputBufferList->mNumberBuffers;
    if (nch > m_numChannels) nch = m_numChannels;

    for (UInt32 f = 0; f < inNumberFrames; f++) {
        for (int c = 0; c < nch; c++) {
            const float* src = static_cast<float*>(
                m_inputBufferList->mBuffers[c].mData);
            m_inputBuffer[f * m_numChannels + c] = (cFloat)src[f];
        }
        /* Pad missing channels with silence. */
        for (int c = nch; c < m_numChannels; c++)
            m_inputBuffer[f * m_numChannels + c] = 0.0;
    }

    /* Clear the interleaved output buffer. */
    memset(m_outputBuffer, 0,
           inNumberFrames * (UInt32)m_numChannels * sizeof(cFloat));

    /* Run the pitch-detection / pass-through processing. */
    if (m_process)
        m_process->process(m_inputBuffer, m_outputBuffer,
                           (int)inNumberFrames, m_numChannels);

    /* Convert interleaved cFloat → non-interleaved float32 for CoreAudio. */
    for (UInt32 b = 0; b < ioData->mNumberBuffers; b++) {
        float* dst = static_cast<float*>(ioData->mBuffers[b].mData);
        int ch = ((int)b < m_numChannels) ? (int)b : m_numChannels - 1;
        for (UInt32 f = 0; f < inNumberFrames; f++)
            dst[f] = (float)m_outputBuffer[f * m_numChannels + ch];
    }

    return noErr;
}

#endif /* __APPLE__ */
