# Polyphonic Pitch Detector for Guitars

This repository hosts a pitch detection application designed for Linux systems, specifically tailored for guitar input. The underlying methodology is based on complex resonators and is optimized for accurate pitch estimation. The theoretical foundation of complex resonators can be found in the article titled "A Computationally Efficient Method for Polyphonic Pitch Estimation" authored by Ruohua Zhou, Joshua D. Reiss, Marco Mattavelli, and Giorgio Zoia.

The system is currently in a developmental phase to incorporate frequency domain effects.
  
## About the Algorithm

The Polyphonic Pitch Detection algorithm was developed in collaboration with Benti SA and REDS (Reconfigurable Embedded Systems) in Yverdon-les-Bains, Switzerland. This algorithm boasts remarkable efficiency in detecting polyphonic pitches for guitar sounds.

The algorithm achieves an average latency of approximately 15 ms, even for lower frequencies. 
The innovation lies in a combined frequency and time domain analysis approach. The time domain analysis leverages the physical properties of vibrating guitar strings to recognize specific features of the incoming signal. A robust logical algorithm then deduces the pitch of incoming notes, even with less than a full wave period.

This algorithm is lightweight enough to run on devices like a Raspberry Pi. It can convert real-time audio input into MIDI sequences with an error possibility of just 2.5% in a 15 ms latency window. By extending the latency to 20 ms, the error potential decreases significantly, approaching 0.5%.

The versatility of this algorithm opens up numerous musical applications. One prominent use case involves extracting note information from incoming sound to apply real-time signal processing techniques. These techniques can manipulate the spectral content of the sound without any perceivable latency, enhancing the expressive connection between musician and instrument.

The repository aims to make this innovative algorithm accessible and has the potential to reshape sound possibilities, making the dream of creating unique and distinctive guitar sounds a reality. The system's compact form factor allows for interaction with smartphones and online communities, ushering in new realms of sonic exploration.

For a visual demonstration of the algorithm, [watch these videos](https://www.youtube.com/playlist?list=PL3pYQ_Ww19BV61bMUF2VkwfdTDds1Mixh).

A C++ version of the algorithm is currently being prepared and is available within this GitHub repository. 

## Installation Requirements

- Linux-based operating system
- ALSA audio system
- Jack Audio Connection Kit
- CMake (version 2.6 or higher)
- wxWidgets library
- pthread
- sndfile
- C++ compiler with SSE4.2 support

## Quick Start

1. Clone the repository:
```
git clone https://github.com/luciamarockmood/pdct_lib.git
```

2. Navigate to the repository directory:
```
mkdir build 
cd build
```

3. Build the project:
```
cmake ..
make
```

4. Run the program (Jack Server must be running):
```
./pdct
```


## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting pull requests.

## License

This project is licensed under GNU General Public License v3.0 - see the LICENSE file for details.

## Support

For questions and support:
- Open an issue on GitHub
- Join our [Telegram channel](https://t.me/luciamarockmood) for updates and community discussions
