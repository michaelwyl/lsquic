from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

# Configure Chrome options
chrome_options = Options()
chrome_options.add_argument("--mute-audio")  
chrome_options.add_argument("--headless")
chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")

# Set up Chrome WebDriver
service = Service("/opt/homebrew/bin/chromedriver")  
driver = webdriver.Chrome(service=service, options=chrome_options)

# Load the video page
video_url = "http://localhost:8000/"
driver.get(video_url)

time.sleep(3)  # Allow page to load

# Find the video element
video = driver.find_element(By.ID, "videoPlayer")

# Start tracking QoE metrics
start_time = time.time()  # Startup time tracking
stall_count = 0
total_stall_time = 0
last_frame_time = 0

# Load and play the video
driver.execute_script("arguments[0].load();", video)
driver.execute_script("arguments[0].play();", video)

# Collect QoE metrics continuously
print("Collecting QoE metrics...")

for i in range(1000000):  
    qoe_metrics = driver.execute_script("""
        let video = arguments[0];
        return {
            currentTime: video.currentTime,
            buffered: video.buffered.length > 0 ? video.buffered.end(video.buffered.length - 1) : 0,
            playbackRate: video.playbackRate,
            droppedFrames: video.getVideoPlaybackQuality().droppedVideoFrames,
            totalFrames: video.getVideoPlaybackQuality().totalVideoFrames,
            fps: video.getVideoPlaybackQuality().totalVideoFrames / (video.currentTime || 1),
            resolution: `${video.videoWidth}x${video.videoHeight}`,
            readyState: video.readyState,  // Indicates buffering state
        };
    """, video)

    # Calculate rebuffering events (stalling)
    if qoe_metrics["readyState"] < 3:  # Video is buffering
        stall_count += 1
        stall_start = time.time()

        while driver.execute_script("return arguments[0].readyState;", video) < 3:
            time.sleep(0.1)

        stall_end = time.time()
        total_stall_time += (stall_end - stall_start)


    # Rebuffer Rate Calculation
    playback_time = qoe_metrics["currentTime"]
    rebuffer_rate = (total_stall_time / playback_time) if playback_time > 0 else 0

    # Print real-time QoE metrics
    print(f"Time: {qoe_metrics['currentTime']:.2f}s, "
          f"Buffered: {qoe_metrics['buffered']:.2f}s, "
          f"Playback Rate: {qoe_metrics['playbackRate']:.2f}, "
          f"Dropped Frames: {qoe_metrics['droppedFrames']}, "
          f"Total Frames: {qoe_metrics['totalFrames']}, "
          f"FPS: {qoe_metrics['fps']:.2f}, "
          f"Resolution: {qoe_metrics['resolution']}, "
          f"Stalls: {stall_count}, "
          f"Total Stall Time: {total_stall_time:.2f}s, "
          f"Rebuffer Rate: {rebuffer_rate:.2%}")

    time.sleep(1)

# Close the browser when finished
driver.quit()