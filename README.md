LiteSpeed QUIC (LSQUIC) Library README
=============================================


Requirements
------------

To build LSQUIC, you need CMake, zlib, and BoringSSL.  The example program
uses libevent to provide the event loop.

Building BoringSSL
------------------

BoringSSL is not packaged; you have to build it yourself.  The process is
straightforward.  You will need `go` installed.

1. Clone BoringSSL by issuing the following command:

```
git clone https://boringssl.googlesource.com/boringssl
cd boringssl
```

You may need to install pre-requisites like zlib and libevent.


2. Compile the library

```
cmake . &&  make
```

Remember where BoringSSL sources are:
```
BORINGSSL=$PWD
```

If you want to build as a library, (necessary to build lsquic itself
as as shared library) do:

```
cmake -DBUILD_SHARED_LIBS=1 . && make
```

Building LSQUIC Library
-----------------------

LSQUIC's `http_client`, `http_server`, and the tests link BoringSSL
libraries statically.  Following previous section, you can build LSQUIC
as follows:

1. Get the source code

```
git clone https://github.com/michaelwyl/lsquic.git
cd lsquic
git submodule update --init
```

2. Compile the library

```
# $BORINGSSL is the top-level BoringSSL directory from the previous step
cmake -DBORINGSSL_DIR=$BORINGSSL .
make
```

Tests
-----------------------
The codebase allows various tests to be performed
- /bin/perf_server/client - benchmarking the performance of QUIC connections (similar to iperf3 in TCP in terms of functionality)
- video streaming QoE data collection discussed in the following steps. 

Prepare Video
-----------------------

You will need to prepare video segments under `/bin/video` for ABR, with a pre-existing `.mp4` file.
```
cd bin/video
MP4Box -add input.mp4#video -new video.mp4
MP4Box -add input.mp4#audio -new audio.mp4
MP4Box -dash 4000 -frag 4000 -rap -segment-name segment_ -out manifest.mpd video.mp4 audio.mp4
```
This will generate the video chunks.

Watch Video
-----------------------

In a terminal run the following to host the video.
```
cd bin
./http_server -s ip_address:port -r ./video -A 2 -c domain_name,path_to_cert.pem,path_to_key.pem
```
To generate SSL certificate for the connection, run
```
cd bin/certificate
openssl genrsa -out cert.key 2048
openssl req -new -key cert.key -out cert.csr -config lsquic.cnf
openssl x509 -req -days 365 -in cert.csr -signkey cert.key -out cert.crt -extensions v3_req -extfile lsquic.cnf
openssl x509 -pubkey -noout -in cert.crt | openssl rsa -pubin -outform der | openssl dgst -sha256 -binary | base64 
```
Copy the output from last command and on another machine, modify the /bin/qoe.py line 11.
```
chrome_options.add_argument("--ignore-certificate-errors-spki-list=dSiDY7LGoozlpLzHmutdwpKP/y2cfN9oh98uNYpNViI=") # substitute the value after "="
```
Then run
```
cd bin
python qoe.py
```
While running the pipeline, BBR parameter will be logged into files
- bw_sampling
- cnwd
- min_rtt
- pacing_rate
- throughput

QoE metrics will be printed out to the stdout. Example:
```
Time: 0.00s, Buffered: 35.99s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 4, FPS: 1112.35, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 0.97s, Buffered: 43.98s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 33, FPS: 34.08, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 1.97s, Buffered: 48.40s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 63, FPS: 31.92, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 2.98s, Buffered: 55.98s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 94, FPS: 31.56, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 3.99s, Buffered: 63.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 124, FPS: 31.06, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 5.00s, Buffered: 63.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 154, FPS: 30.80, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 6.02s, Buffered: 63.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 185, FPS: 30.75, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 7.03s, Buffered: 63.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 215, FPS: 30.60, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 8.03s, Buffered: 64.17s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 245, FPS: 30.51, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 9.04s, Buffered: 64.17s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 275, FPS: 30.43, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 10.04s, Buffered: 73.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 306, FPS: 30.46, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 11.06s, Buffered: 73.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 336, FPS: 30.39, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
Time: 12.07s, Buffered: 73.23s, Playback Rate: 1.00, Dropped Frames: 0 (0.00%), Total Frames: 366, FPS: 30.33, Resolution: 1920x1080, Stalls: 0, Total Stall Time: 0.00s, Rebuffer Rate: 0.00%
```
