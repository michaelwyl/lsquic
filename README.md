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
Specific instructions on generating the certificates will be added later.

On another machine, run
```
cd bin
python qoe.py
```
QoE metrics will be printed out to the stdout.
