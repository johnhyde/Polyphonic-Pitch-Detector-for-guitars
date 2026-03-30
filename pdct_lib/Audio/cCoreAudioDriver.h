
/*
 * File:   cCoreAudioDriver.h
 *
 * macOS CoreAudio AUHAL driver — drop-in replacement for cJackdDriver.
 * Uses a single Hardware Abstraction Layer (AUHAL) AudioUnit configured
 * for simultaneous stereo input (bus 1) and output (bus 0) on the same
 * device.  The render callback pulls input, calls the attached
 * cJackProcess, then writes output — matching the Jack process-callback
 * contract exactly.
 */

#ifndef CCOREAUDIODRIVER_H
#define CCOREAUDIODRIVER_H

#ifdef __APPLE__

#include "common_type.h"
#include "cJackProcess.h"

#include <AudioUnit/AudioUnit.h>
#include <CoreAudio/CoreAudio.h>

class cCoreAudioDriver {
public:
    cCoreAudioDriver();
    virtual ~cCoreAudioDriver();

    int  open(cString name);
    int  close();
    void attachProcess(cJackProcess* process);

    /* Called from the CoreAudio render callback — do not call directly. */
    OSStatus onRender(AudioUnitRenderActionFlags* ioActionFlags,
                      const AudioTimeStamp*        inTimeStamp,
                      UInt32                        inOutputBusNumber,
                      UInt32                        inNumberFrames,
                      AudioBufferList*              ioData);

private:
    AudioUnit        m_audioUnit;
    cJackProcess*    m_process;

    int              m_bufferSize;   /* frames per callback             */
    int              m_numChannels;  /* channels (stereo = 2)           */

    cFloat*          m_inputBuffer;  /* interleaved, size=bufSize*nch   */
    cFloat*          m_outputBuffer; /* interleaved, size=bufSize*nch   */

    /* Non-interleaved scratch buffers used when pulling input via
     * AudioUnitRender.  mData pointers are owned by this object.       */
    AudioBufferList* m_inputBufferList;
};

#endif /* __APPLE__ */
#endif /* CCOREAUDIODRIVER_H */
