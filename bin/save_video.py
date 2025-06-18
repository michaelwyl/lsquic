#!/usr/bin/env python3
import time
import csv
import base64
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

chrome_options = Options()
chrome_options.add_argument("--ignore-certificate-errors")
chrome_options.add_argument("--ignore-certificate-errors-spki-list=dSiDY7LGoozlpLzHmutdwpKP/y2cfN9oh98uNYpNViI=")
chrome_options.add_argument("--ignore-ssl-errors")
chrome_options.add_argument("--enable-quic")
chrome_options.add_argument("--host-resolver-rules=MAP quic.local 45.76.170.255")
chrome_options.add_argument("--origin-to-force-quic-on=quic.local:5201")
chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--allow-running-insecure-content")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--headless")

service = Service("/opt/homebrew/bin/chromedriver")
driver  = webdriver.Chrome(service=service, options=chrome_options)


driver.set_script_timeout(180)

driver.get("https://quic.local:5201/index.html")
time.sleep(10)                                       
video = driver.find_element(By.ID, "videoPlayer")

# # get the list of available ABR algorithms & their IDs
# abr_settings = driver.execute_script("""
#   const player = dashjs.MediaPlayer().create();
#   return player.getSettings().streaming.abr;
# """)
# print(abr_settings)

driver.execute_script("""
   if (!window.dashjs) {
     const s = document.createElement('script');
     s.src = 'https://cdn.dashjs.org/latest/dash.all.min.js';
     s.crossOrigin = 'anonymous';
     document.head.appendChild(s);
   }
 """)
time.sleep(1)  # give dash.js time to load

# (2) Create the player, turn off all rules except BOLA as an example
driver.execute_script("""
(() => {
   const v = document.getElementById('videoPlayer');
   const mpd = 'https://quic.local:5201/manifest.mpd';
   const player = dashjs.MediaPlayer().create();

   player.updateSettings({
     streaming: {
       abr: {
         rules: {
           throughputRule:         { active: false },
           bolaRule:               { active: true  },  // <— use BOLA only
           insufficientBufferRule: { active: false },
           abandonRequestsRule:    { active: false },
           droppedFramesRule:      { active: false },
           l2ARule:                { active: false },
           loLPRule:               { active: false },
           switchHistoryRule:      { active: false }
         }
       }
     }
   });

   player.initialize(v, mpd, true);
   window.__dash_player = player;
 })();
 """)

# (3) Verify on the Python side what the player is actually using:
current_abr = driver.execute_script(
  "return window.__dash_player.getSettings().streaming.abr;"
)
print("Current ABR config:", current_abr)


driver.execute_script("""
(() => {
  const v = arguments[0];
  if (!v) return;
  v.muted = true; v.play();

  if (window.__recorder_started) return;           
  window.__recorder_started = true;

  const stream = v.captureStream();
  const rec    = new MediaRecorder(stream, {mimeType:'video/webm;codecs=vp9'});
  window.__chunks = [];
  rec.ondataavailable = e => window.__chunks.push(e.data);
  rec.start(1000);                                   
  window.__recorder = rec;
})();
""", video)


csv_file   = open("qoe_metrics.csv", "w", newline="")
csv_writer = csv.writer(csv_file)
csv_writer.writerow([
    "wall_clock", "playback_time", "buffered", "playback_rate",
    "dropped_frames", "total_frames", "fps", "resolution",
    "stall_count", "total_stall_time", "rebuffer_rate"
])

stall_count = 0
total_stall_time = 0
wall_clock_start = time.time()


try:
    while True:
        qoe = driver.execute_script("""
          const v = arguments[0];
          const q = v.getVideoPlaybackQuality();
          return {
            currentTime:  v.currentTime,
            buffered:     (v.buffered.length ? v.buffered.end(v.buffered.length-1) : 0),
            rate:         v.playbackRate,
            dropped:      q.droppedVideoFrames,
            total:        q.totalVideoFrames,
            fps:          (q.totalVideoFrames / (v.currentTime || 1)),
            res:          `${v.videoWidth}x${v.videoHeight}`,
            readyState:   v.readyState,
            ended:        v.ended
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

        # Print to console
        print(f"t={qoe['currentTime']:.1f}s  "
              f"buf={qoe['buffered']:.1f}s  "
              f"rate={qoe['rate']:.2f}  "
              f"fps={qoe['fps']:.1f}  "
              f"drop={frame_drop_pct:.1f}%  "
              f"res={qoe['res']}  "
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