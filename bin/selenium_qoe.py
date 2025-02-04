from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

chrome_options = Options()
chrome_options.add_argument("--mute-audio")  
chrome_options.add_argument("--headless")
chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")

service = Service("/opt/homebrew/bin/chromedriver")  
driver = webdriver.Chrome(service=service, options=chrome_options)

video_url = "http://localhost:8000/"
driver.get(video_url)

time.sleep(3)

video = driver.find_element(By.ID, "videoPlayer")

driver.execute_script("arguments[0].load();", video)

driver.execute_script("arguments[0].play();", video)

for i in range(1000000):
    current_time = driver.execute_script("return arguments[0].currentTime;", video)
    
    # Fixing the buffering retrieval logic
    buffered = driver.execute_script("""
        if (arguments[0].buffered.length > 0) {
            return arguments[0].buffered.end(arguments[0].buffered.length - 1);
        } else {
            return 0;
        }
    """, video)
    
    playback_rate = driver.execute_script("return arguments[0].playbackRate;", video)
    
    print(f"Time: {current_time:.2f}s, Buffered: {buffered:.2f}s, Playback Rate: {playback_rate:.2f}")
    time.sleep(1)

# Close the browser
driver.quit()