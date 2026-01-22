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

For QUIC
```
cd bin
./http_server -s ip_address:port -r ./video -A 2 -c domain_name,path_to_cert.pem,path_to_key.pem
```

For TCP
```
cd bin/video
python3 -m http.server 5201 --bind 0.0.0.0
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
python watch_and_save.py tcp/quic
```
While running the pipeline, BBR parameter will be logged into files
- bw_sampling
- cwnd
- min_rtt
- pacing_rate
- throughput

QoE metrics will be printed out to the stdout and saved in a file. Example:
```
t=0.0s buf=15.4s bitrate=0kbps switches=0 fps=353.4 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=1.0s buf=15.4s bitrate=0kbps switches=0 fps=34.1 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=2.0s buf=15.4s bitrate=0kbps switches=0 fps=31.9 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=3.0s buf=15.4s bitrate=0kbps switches=0 fps=31.2 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=4.1s buf=15.4s bitrate=0kbps switches=0 fps=31.0 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=5.1s buf=15.4s bitrate=0kbps switches=0 fps=30.8 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=6.1s buf=15.4s bitrate=0kbps switches=0 fps=30.7 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=7.1s buf=15.4s bitrate=0kbps switches=0 fps=30.6 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=8.1s buf=15.4s bitrate=0kbps switches=0 fps=30.5 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=9.1s buf=15.4s bitrate=0kbps switches=0 fps=30.5 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=10.1s buf=15.4s bitrate=0kbps switches=0 fps=30.4 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=11.1s buf=15.4s bitrate=0kbps switches=0 fps=30.3 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=12.2s buf=15.4s bitrate=0kbps switches=0 fps=30.4 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=13.2s buf=15.4s bitrate=0kbps switches=0 fps=30.3 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=14.2s buf=15.4s bitrate=0kbps switches=0 fps=30.3 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=15.2s buf=15.4s bitrate=0kbps switches=0 fps=30.3 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
t=15.4s buf=15.4s bitrate=0kbps switches=0 fps=30.0 drop=0.0% stalls=0 totalStall=0.0s rebuffer rate=0.0%
```
Note: bitrate calculation needs to be updated, current calculation is incorrect.
