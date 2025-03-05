from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By  # ← Add this line
from selenium.webdriver.chrome.options import Options
import time

# Configure Chrome options
chrome_options = Options()
chrome_options.add_argument("--ignore-certificate-errors")
chrome_options.add_argument("--allow-insecure-localhost")
chrome_options.add_argument("--ignore-ssl-errors")
chrome_options.add_argument("--enable-quic")
chrome_options.add_argument("--origin-to-force-quic-on=mytestserver.local:4433")

chrome_options.add_argument("--disable-web-security")
chrome_options.add_argument("--allow-running-insecure-content")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--headless")
chrome_options.add_argument("--ignore-certificate-errors")


# Path to ChromeDriver
service = Service("/opt/homebrew/bin/chromedriver")

# Start WebDriver
driver = webdriver.Chrome(service=service, options=chrome_options)


print("Attempting to connect to https://mytestserver.local:4433...")
driver.get("https://mytestserver.local:4433/index.html")

# Wait for video element to load
time.sleep(5)

video = driver.find_element(By.ID, "videoPlayer")

# **Ensure video starts playing**
play_script = """
var video = arguments[0];
if (video) {
    video.muted = true;  // Mute required for autoplay
    video.play();
    return video.paused ? 'Video did not start' : 'Video is playing';
} else {
    return 'No video element found';
}
"""
result = driver.execute_script(play_script, video)
print(f"🔹 Play Status: {result}")

if result == "Video did not start":
    print("⚠️ Video failed to play. Check browser settings.")

# **Start QoE Metric Collection**
start_time = time.time()  # Startup time tracking
stall_count = 0
total_stall_time = 0

print("\n🎥 QoE Metric Collection Started...")

while True:
    qoe_metrics = driver.execute_script("""
        let video = arguments[0];
        let quality = video.getVideoPlaybackQuality();
        return {
            currentTime: video.currentTime,
            buffered: video.buffered.length > 0 ? video.buffered.end(video.buffered.length - 1) : 0,
            playbackRate: video.playbackRate,
            droppedFrames: quality.droppedVideoFrames,
            totalFrames: quality.totalVideoFrames,
            fps: quality.totalVideoFrames / (video.currentTime || 1),
            resolution: `${video.videoWidth}x${video.videoHeight}`,
            readyState: video.readyState,  // Indicates buffering state
        };
    """, video)

    # **Detect Buffering (Stalling)**
    if qoe_metrics["readyState"] < 3:  # Video is buffering
        stall_count += 1
        stall_start = time.time()

        while driver.execute_script("return arguments[0].readyState;", video) < 3:
            time.sleep(0.1)

        stall_end = time.time()
        stall_duration = stall_end - stall_start
        total_stall_time += stall_duration

    # **Calculate Rebuffer Rate**
    playback_time = qoe_metrics["currentTime"]
    rebuffer_rate = (total_stall_time / playback_time) if playback_time > 0 else 0

    # **Calculate Frame Drop Rate**
    total_frames = qoe_metrics["totalFrames"]
    dropped_frames = qoe_metrics["droppedFrames"]
    frame_drop_rate = (dropped_frames / total_frames) * 100 if total_frames > 0 else 0

    # **Print QoE Metrics**
    print(f"Time: {qoe_metrics['currentTime']:.2f}s, "
          f"Buffered: {qoe_metrics['buffered']:.2f}s, "
          f"Playback Rate: {qoe_metrics['playbackRate']:.2f}, "
          f"Dropped Frames: {qoe_metrics['droppedFrames']} ({frame_drop_rate:.2f}%), "
          f"Total Frames: {qoe_metrics['totalFrames']}, "
          f"FPS: {qoe_metrics['fps']:.2f}, "
          f"Resolution: {qoe_metrics['resolution']}, "
          f"Stalls: {stall_count}, "
          f"Total Stall Time: {total_stall_time:.2f}s, "
          f"Rebuffer Rate: {rebuffer_rate:.2%}")

    time.sleep(1)  # Update every second

# Close the browser when finished
driver.quit()