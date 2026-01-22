import time
import csv
import base64
import json
import sys
import argparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

def setup_chrome_options(protocol):
    """Setup Chrome options based on transport protocol"""
    chrome_options = Options()
    
    if protocol.lower() == 'quic':
        # QUIC-specific options from save_video.py
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
        
    elif protocol.lower() == 'tcp':
        # TCP-specific options from tcp_selenium.py
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--ignore-ssl-errors")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--enable-logging")
        chrome_options.add_argument("--v=1")
        
        # Enable performance logging in newer Selenium versions
        chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    else:
        raise ValueError(f"Unsupported protocol: {protocol}. Use 'tcp' or 'quic'")
    
    return chrome_options

def get_target_url(protocol):
    """Get the target URL based on transport protocol"""
    if protocol.lower() == 'quic':
        return "https://quic.local:5201/index.html"
    elif protocol.lower() == 'tcp':
        return "http://45.76.170.255:5201/index.html"
    else:
        raise ValueError(f"Unsupported protocol: {protocol}")

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Watch and save video with specified transport protocol')
    parser.add_argument('protocol', choices=['tcp', 'quic'], 
                       help='Transport protocol to use (tcp or quic)')
    args = parser.parse_args()
    
    print(f"Starting video monitoring with {args.protocol.upper()} protocol...")
    
    # Setup Chrome options based on protocol
    chrome_options = setup_chrome_options(args.protocol)
    
    # Setup Chrome driver
    service = Service("/opt/homebrew/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_script_timeout(180)  # up to 3 minutes for async JS
    
    # Get target URL based on protocol
    target_url = get_target_url(args.protocol)
    
    # Navigate & load page
    driver.get(target_url)
    time.sleep(10)  # allow DOM, dash.js, and media to load
    video = driver.find_element(By.ID, "videoPlayer")
    
    # TODO: Add the rest of the video monitoring logic here
    # This would include the DASH player setup, quality monitoring, 
    # CSV logging, and video recording functionality
    
    print(f"Successfully loaded page with {args.protocol.upper()} protocol")
    
    # ─── 1) Install quality-switch listener for oscillation logging ───────
    driver.execute_script("""
    (() => {
    if (!window.__quality_switches) {
        window.__quality_switches = [];
        const player = dashjs.MediaPlayer().create();
        player.on(
        dashjs.MediaPlayer.events.QUALITY_CHANGE_RENDERED,
        e => window.__quality_switches.push({
            timestamp:   e.time,
            oldQuality:  e.oldQuality,
            newQuality:  e.newQuality
        })
        );
    }
    })();
    """)

    # ─── 2) Inject dash.js and configure ABR algorithm (BOLA example) ─────
    driver.execute_script("""
    (() => {
    if (!window.dashjs) {
        const s = document.createElement('script');
        s.src = 'https://cdn.dashjs.org/latest/dash.all.min.js';
        s.crossOrigin = 'anonymous';
        document.head.appendChild(s);
    }
    })();
    """)
    time.sleep(1)  # wait for dash.js to load

    # Configure and initialize the DASH player
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
            bolaRule:               { active: true  },
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

    # Verify current ABR settings
    current_abr = driver.execute_script("return window.__dash_player.getSettings().streaming.abr;")
    print("Current ABR config:", json.dumps(current_abr, indent=2))

    # ─── 3) Inject MediaRecorder for local recording ─────────────────────
    driver.execute_script("""
    ((v) => {
    v.muted = true;
    v.play();
    if (window.__recorder_started) return;
    window.__recorder_started = true;

    const stream = v.captureStream();
    const rec = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9' });
    window.__chunks = [];
    rec.ondataavailable = e => window.__chunks.push(e.data);
    rec.start(1000);  // flush every 1s
    window.__recorder = rec;
    })(arguments[0]);
    """, video)

    # ───── Setup CSV for QoE metrics ──────────────────────────────────────
    csv_file = open(f"qoe_metrics_{args.protocol}.csv", "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow([
    "wall_clock", "playback_time", "buffered", "playback_rate",
    "bitrate_kbps", "quality_switch_count",
    "dropped_frames", "total_frames", "fps", "resolution",
    "stall_count", "total_stall_time", "rebuffer_rate"
    ])

    stall_count = 0
    total_stall_time = 0.0
    wall_clock_start = time.time()

    # ───────── Main loop: QoE, bitrate, oscillation logging ──────────────
    try:
        while True:
            # 1) Basic QoE metrics
            q = driver.execute_script("""
            const v = arguments[0];
            const q = v.getVideoPlaybackQuality();
            return {
                currentTime: v.currentTime,
                buffered:    v.buffered.length ? v.buffered.end(v.buffered.length-1) : 0,
                rate:        v.playbackRate,
                dropped:     q.droppedVideoFrames,
                total:       q.totalVideoFrames,
                fps:         q.totalVideoFrames / (v.currentTime || 1),
                res:         `${v.videoWidth}x${v.videoHeight}`,
                readyState:  v.readyState,
                ended:       v.ended
            };
            """, video)

            # 2) Stall detection
            if q["readyState"] < 3:
                stall_count += 1
                t0 = time.time()
                while driver.execute_script("return arguments[0].readyState;", video) < 3:
                    time.sleep(0.1)
                total_stall_time += time.time() - t0

            # 3) Playback bitrate
            bitrate_kbps = driver.execute_script(
            "return (window.__dash_player.getCurrentTrackFor('video') || {}).bitrate || 0;"
            )

            # 4) Quality switch count
            switch_count = driver.execute_script(
            "return (window.__quality_switches || []).length;"
            )

            # 5) Derived metrics
            rebuffer_rate = total_stall_time / q["currentTime"] if q["currentTime"] else 0
            drop_pct = (q["dropped"] / q["total"] * 100) if q["total"] else 0

            # 6) Print summary
            print(f"t={q['currentTime']:.1f}s buf={q['buffered']:.1f}s "
                f"bitrate={bitrate_kbps}kbps switches={switch_count} "
                f"fps={q['fps']:.1f} drop={drop_pct:.1f}% "
                f"stalls={stall_count} totalStall={total_stall_time:.1f}s "
                f"rebuffer rate={rebuffer_rate*100:.1f}%")

            # 7) Write CSV
            csv_writer.writerow([
            round(time.time() - wall_clock_start,2),
            round(q['currentTime'],2), round(q['buffered'],2), round(q['rate'],2),
            bitrate_kbps, switch_count,
            q['dropped'], q['total'], round(q['fps'],2), q['res'],
            stall_count, round(total_stall_time,2), round(rebuffer_rate,4)
            ])

            if q['ended']:
                print("\n🎬 Video ended – finishing up…")
                break

            time.sleep(1)

    finally:
        csv_file.close()

        # Stop recorder and save webm
        data_url = driver.execute_async_script("""
        const done = arguments[0];
        if (!window.__recorder) { done(null); return; }
        if (window.__video_data_url) { done(window.__video_data_url); return; }
        const finish = () => {
            try {
            const blob = new Blob(window.__chunks||[], {type:'video/webm'});
            if (!blob.size) { done(null); return; }
            const fr = new FileReader();
            fr.onloadend = () => { window.__video_data_url = fr.result; done(fr.result); };
            fr.readAsDataURL(blob);
            } catch(e) { done(null); }
        };
        if (window.__recorder.state === 'inactive') { finish(); return; }
        let ended = false;
        window.__recorder.ondataavailable = e => window.__chunks.push(e.data);
        window.__recorder.onstop = () => { ended = true; finish(); };
        window.__recorder.requestData(); window.__recorder.stop();
        setTimeout(() => { if (!ended) done(null); }, 20000);
        """
        )

        if data_url:
            _, b64 = data_url.split(',',1)
            with open(f"recorded_video_{args.protocol}.webm","wb") as f:
                f.write(base64.b64decode(b64))
            print("📼  recorded_video.webm saved ✔")
        else:
            print("⚠️  No recording produced.")

        # Save quality-switch log
        switches = driver.execute_script("return window.__quality_switches || [];"
        )
        with open(f"switches_{args.protocol}.log","w") as f:
            json.dump(switches, f, indent=2)
        print(f"🗒  {len(switches)} switches logged to switches.log")
    # Cleanup
    driver.quit()

if __name__ == "__main__":
    main()
