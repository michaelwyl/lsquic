#!/usr/bin/env python3
import time
import csv
import base64
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

chrome_options = Options()
# Removed QUIC-specific arguments
chrome_options.add_argument("--ignore-certificate-errors")
chrome_options.add_argument("--ignore-ssl-errors")
chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--allow-running-insecure-content")
chrome_options.add_argument("--no-sandbox")
# chrome_options.add_argument("--headless")
chrome_options.add_argument("--enable-logging")
chrome_options.add_argument("--v=1")

# Enable performance logging in newer Selenium versions
chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

service = Service("/opt/homebrew/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=chrome_options)

driver.set_script_timeout(180)

# Changed to localhost HTTP server (adjust URL as needed)
driver.get("http://45.76.170.255:5201/index.html")
time.sleep(10)                                       
video = driver.find_element(By.ID, "videoPlayer")

# Enhanced JavaScript to capture DASH player events and ABR decisions
driver.execute_script("""
(() => {
  const v = arguments[0];
  if (!v) return;
  v.muted = true; v.play();

  if (window.__recorder_started) return;           
  window.__recorder_started = true;

  // Setup video recording
  const stream = v.captureStream();
  const rec    = new MediaRecorder(stream, {mimeType:'video/webm;codecs=vp9'});
  window.__chunks = [];
  rec.ondataavailable = e => window.__chunks.push(e.data);
  rec.start(1000);                                   
  window.__recorder = rec;

  // ABR event tracking
  window.__abr_events = [];
  window.__segment_downloads = [];
  window.__last_quality = null;

  // Try to detect DASH player (dash.js) - different versions have different APIs
  if (window.dashjs && window.dashjs.MediaPlayer) {
    // First try to get player instance through the more common pattern
    let player = null;
    
    // Try to find dash instance using common methods
    try {
      // Modern versions might have a factory or instance directly on dashjs
      if (typeof window.dashjs.MediaPlayer === 'function') {
        // Check if there's an existing instance via the getInstance method
        if (typeof window.dashjs.MediaPlayer.getInstance === 'function') {
          player = window.dashjs.MediaPlayer.getInstance();
        }
      }
      
      // Alternative way: look for data attributes on the video element
      if (!player && v.getAttribute('data-dashjs-player') !== null) {
        player = window.dashjs.MediaPlayer().getVideoElement(v);
      }
      
      // Last resort: check if any instance is attached to the video element
      if (!player) {
        const dashInfo = v.dataset.dashPlayer || v.getAttribute('data-dashjs-player');
        if (dashInfo) {
          player = window.dashjs.MediaPlayer();
        }
      }
    } catch (e) {
      console.error('Error finding dash.js player:', e);
    }
    
    // If we found a player instance, set up event listeners
    if (player) {
      console.log('Found dash.js player instance');
      
      // Listen for quality change events if the API supports it
      if (typeof player.on === 'function') {
        try {
          // Listen for quality change events
          player.on('qualityChangeRendered', (e) => {
            const event = {
              timestamp: Date.now(),
              type: 'quality_change',
              mediaType: e.mediaType,
              streamId: e.streamId,
              oldQuality: e.oldQuality,
              newQuality: e.newQuality,
              bitrate: e.newQuality ? e.newQuality.bitrate : null,
              resolution: e.newQuality ? `${e.newQuality.width}x${e.newQuality.height}` : null
            };
            window.__abr_events.push(event);
            console.log('ABR Quality Change:', event);
          });

          // Listen for buffer events
          player.on('bufferStateChanged', (e) => {
            const event = {
              timestamp: Date.now(),
              type: 'buffer_state',
              mediaType: e.mediaType,
              state: e.state
            };
            window.__abr_events.push(event);
          });

          // Listen for fragment loading events
          player.on('fragmentLoadingCompleted', (e) => {
            const event = {
              timestamp: Date.now(),
              type: 'segment_downloaded',
              mediaType: e.mediaType,
              url: e.request.url,
              size: e.response.length,
              quality: e.request.quality,
              bitrate: e.request.quality ? e.request.quality.bitrate : null,
              downloadTime: e.response.requestEndDate - e.response.requestStartDate
            };
            window.__segment_downloads.push(event);
          });
        } catch (e) {
          console.error('Error setting up dash.js event listeners:', e);
        }
      }

      // Get current quality info
      window.__getCurrentQuality = () => {
        try {
          if (typeof player.getQualityFor === 'function' && 
              typeof player.getBitrateInfoListFor === 'function') {
            const videoQuality = player.getQualityFor('video');
            const audioQuality = player.getQualityFor('audio');
            const bitrateInfoListFor = player.getBitrateInfoListFor('video');
            
            return {
              video: {
                currentQuality: videoQuality,
                availableQualities: bitrateInfoListFor,
                currentBitrate: bitrateInfoListFor[videoQuality] ? bitrateInfoListFor[videoQuality].bitrate : null
              },
              audio: {
                currentQuality: audioQuality
              }
            };
          }
          return null;
        } catch (e) {
          console.error('Error getting quality info:', e);
          return null;
        }
      };
    }
  }

  // Fallback: Monitor video element properties for quality changes
  let lastWidth = v.videoWidth, lastHeight = v.videoHeight;
  setInterval(() => {
    if (v.videoWidth !== lastWidth || v.videoHeight !== lastHeight) {
      const event = {
        timestamp: Date.now(),
        type: 'resolution_change',
        oldResolution: `${lastWidth}x${lastHeight}`,
        newResolution: `${v.videoWidth}x${v.videoHeight}`
      };
      window.__abr_events.push(event);
      lastWidth = v.videoWidth;
      lastHeight = v.videoHeight;
    }
  }, 1000);
})();
""", video)

csv_file   = open("qoe_metrics.csv", "w", newline="")
csv_writer = csv.writer(csv_file)
csv_writer.writerow([
    "wall_clock", "playback_time", "buffered", "playback_rate",
    "dropped_frames", "total_frames", "fps", "resolution",
    "stall_count", "total_stall_time", "rebuffer_rate"
])

# Additional CSV for ABR events
abr_csv_file = open("abr_events.csv", "w", newline="")
abr_csv_writer = csv.writer(abr_csv_file)
abr_csv_writer.writerow([
    "timestamp", "wall_clock", "event_type", "media_type", "old_quality", 
    "new_quality", "bitrate", "resolution", "url", "size", "download_time"
])

# Additional CSV for segment downloads
segment_csv_file = open("segment_downloads.csv", "w", newline="")
segment_csv_writer = csv.writer(segment_csv_file)
segment_csv_writer.writerow([
    "timestamp", "wall_clock", "url", "size", "bitrate", "download_time", "media_type"
])

stall_count = 0
total_stall_time = 0
wall_clock_start = time.time()
last_processed_abr_events = 0
last_processed_segments = 0

try:
    while True:
        # Get network logs for segment downloads
        logs = driver.get_log('performance')
        for log in logs:
            try:
                message = json.loads(log['message'])
                if message['message']['method'] == 'Network.responseReceived':
                    url = message['message']['params']['response']['url']
                    if '.m4s' in url or '.mp4' in url:
                        response_data = message['message']['params']['response']
                        segment_csv_writer.writerow([
                            log['timestamp'],
                            round(time.time() - wall_clock_start, 2),
                            url,
                            response_data.get('encodedDataLength', 0),
                            'unknown',  # bitrate not directly available from network logs
                            'unknown',  # download time calculation would need request start
                            'video' if 'video' in url else 'audio' if 'audio' in url else 'unknown'
                        ])
            except (json.JSONDecodeError, KeyError):
                continue

        # Get ABR events from JavaScript
        abr_events = driver.execute_script("return window.__abr_events || [];")
        segment_downloads = driver.execute_script("return window.__segment_downloads || [];")
        
        # Process new ABR events
        new_abr_events = abr_events[last_processed_abr_events:]
        for event in new_abr_events:
            abr_csv_writer.writerow([
                event.get('timestamp', ''),
                round(time.time() - wall_clock_start, 2),
                event.get('type', ''),
                event.get('mediaType', ''),
                event.get('oldQuality', ''),
                event.get('newQuality', ''),
                event.get('bitrate', ''),
                event.get('resolution', ''),
                event.get('url', ''),
                event.get('size', ''),
                event.get('downloadTime', '')
            ])
            
            # Print significant ABR events
            if event.get('type') == 'quality_change':
                print(f"🔄 ABR Quality Change: {event.get('resolution', 'unknown')} @ {event.get('bitrate', 'unknown')} bps")
        
        # Process new segment downloads
        new_segments = segment_downloads[last_processed_segments:]
        for segment in new_segments:
            print(f"📥 Segment: {segment.get('url', '')[-20:]} | {segment.get('bitrate', 'unknown')} bps | {segment.get('downloadTime', 'unknown')}ms")
        
        last_processed_abr_events = len(abr_events)
        last_processed_segments = len(segment_downloads)

        # Regular QoE metrics
        qoe = driver.execute_script("""
          const v = arguments[0];
          const q = v.getVideoPlaybackQuality();
          
          // Get current DASH quality info if available
          let currentQualityInfo = null;
          if (window.__getCurrentQuality) {
            currentQualityInfo = window.__getCurrentQuality();
          }
          
          return {
            currentTime:  v.currentTime,
            buffered:     (v.buffered.length ? v.buffered.end(v.buffered.length-1) : 0),
            rate:         v.playbackRate,
            dropped:      q.droppedVideoFrames,
            total:        q.totalVideoFrames,
            fps:          (q.totalVideoFrames / (v.currentTime || 1)),
            res:          `${v.videoWidth}x${v.videoHeight}`,
            readyState:   v.readyState,
            ended:        v.ended,
            qualityInfo:  currentQualityInfo
          };
        """, video)

        if qoe["readyState"] < 3:
            stall_count += 1
            t0 = time.time()
            while driver.execute_script("return arguments[0].readyState;", video) < 3:
                time.sleep(0.1)
            total_stall_time += time.time() - t0

        # Rates
        rebuffer_rate = (total_stall_time / qoe["currentTime"]) if qoe["currentTime"] else 0
        frame_drop_pct = (qoe["dropped"] / qoe["total"] * 100) if qoe["total"] else 0

        # Print to console with ABR info
        current_bitrate = ""
        if qoe.get('qualityInfo') and qoe['qualityInfo']['video']['currentBitrate']:
            current_bitrate = f" | {qoe['qualityInfo']['video']['currentBitrate']}bps"
            
        print(f"t={qoe['currentTime']:.1f}s  "
              f"buf={qoe['buffered']:.1f}s  "
              f"rate={qoe['rate']:.2f}  "
              f"fps={qoe['fps']:.1f}  "
              f"drop={frame_drop_pct:.1f}%  "
              f"res={qoe['res']}{current_bitrate}  "
              f"stalls={stall_count}  "
              f"stall_time={total_stall_time:.1f}s")

        # Write CSV
        csv_writer.writerow([
            round(time.time() - wall_clock_start, 2),
            round(qoe["currentTime"], 2),
            round(qoe["buffered"], 2),
            round(qoe["rate"], 2),
            qoe["dropped"], qoe["total"],
            round(qoe["fps"], 2),
            qoe["res"],
            stall_count,
            round(total_stall_time, 2),
            round(rebuffer_rate, 4)
        ])

        # Exit when video finished (or set your own duration trigger)
        if qoe["ended"]:
            print("\nVideo ended – finishing up…")
            break

        time.sleep(1)

finally:
    csv_file.close()
    abr_csv_file.close()
    segment_csv_file.close()

    data_url = driver.execute_async_script("""
    const done = arguments[0];

    // Graceful fallbacks
    if (!window.__recorder)              { done(null); return; }
    if (window.__video_data_url)         { done(window.__video_data_url); return; }

    // Helper: turn the chunks we have into a data-URL and resolve
    const finish = () => {
        try {
            const blob   = new Blob(window.__chunks || [], {type:'video/webm'});
            if (!blob.size) { done(null); return; }          // nothing captured
            const fr = new FileReader();
            fr.onloadend = () => { window.__video_data_url = fr.result; done(fr.result); };
            fr.readAsDataURL(blob);
        } catch(e) { done(null); }
    };

    // If already inactive, just finish
    if (window.__recorder.state === 'inactive') { finish(); return; }

    // Otherwise stop → flush → finish
    let ended = false;
    window.__recorder.ondataavailable = e => { window.__chunks.push(e.data); };
    window.__recorder.onstop          = () => { ended = true; finish(); };

    window.__recorder.requestData();   // force final chunk
    window.__recorder.stop();

    // Safety valve: after 20 s give up and return null
    setTimeout(() => { if (!ended) done(null); }, 20000);
    """)

    if data_url:
        header, b64 = data_url.split(',', 1)
        with open("recorded_video.webm", "wb") as f:
            f.write(base64.b64decode(b64))
        print("recorded_video.webm saved ✔")

    driver.quit()