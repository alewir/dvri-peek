Discovering RTSP Streams on a Local Network and Capturing in Python
Main Takeaway
It is possible to discover RTSP streams from cameras on your local network using network scanning techniques and to capture those streams in Python. However, automatic RTSP stream discovery is not always trivial, as most IP cameras do not broadcast their RTSP URLs openly. You typically need to identify devices on the network, probe for open ports (especially 554/tcp), and then try default RTSP paths.

Python offers robust libraries for capturing and processing RTSP streams—most notably, OpenCV and FFmpeg-based wrappers.

1. Discovering RTSP Streams on a Local Network
a. Device Discovery
Use network scanning tools to discover devices on the local network.

Popular Python modules: scapy, arp, socket, or external tools like nmap.

Target common IP camera ports like 554 (RTSP default), 80 (HTTP), 8080, 8554, etc.

Example device scan with nmap (command-line):

bash
nmap -p 554 --open 192.168.1.0/24
This finds devices with RTSP ports open.

b. Service Identification
After finding devices with RTSP ports open, try to connect to the RTSP service.

RTSP URLs are not standardized but often look like:
rtsp://username:password@IP:554/path
Common paths: /live.sdp, /mpeg4, /h264, /video, /cam/realmonitor

c. Automated Discovery Tools
ONVIF protocol: Many modern IP cameras support ONVIF, which can expose RTSP URLs programmatically.

Python package onvif_zeep or onvif-py can help you discover and interact with ONVIF devices.

Simple ONVIF camera discovery with Python:

python
from onvif import ONVIFCamera

# Replace with IP, port, username, password
camera = ONVIFCamera('192.168.1.15', 80, 'admin', 'password')
media_service = camera.create_media_service()
profiles = media_service.GetProfiles()
profile = profiles[0]
rtsp_url = media_service.GetStreamUri({'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}, 'ProfileToken': profile.token})
print(rtsp_url.Uri)
2. Capturing RTSP Streams with Python
a. Using OpenCV
OpenCV's VideoCapture can grab frames directly from RTSP:

python
import cv2

rtsp_url = 'rtsp://username:password@ip:554/stream'
cap = cv2.VideoCapture(rtsp_url)
while True:
    ret, frame = cap.read()
    if not ret:
        break
    # Process frame (e.g., display, save)
    cv2.imshow('RTSP Stream', frame)
    if cv2.waitKey(1) == ord('q'):
        break
cap.release()
cv2.destroyAllWindows()
b. Using FFmpeg/PyAV
PyAV and python-ffmpeg support more complex situations, lower-level control, or for saving/transcoding streams.

Example with PyAV:

python
import av

container = av.open('rtsp://username:password@ip:554/stream')
for frame in container.decode(video=0):
    # Process frames here
    image = frame.to_ndarray(format='bgr24')
3. Summary and Recommendations
Discovery: Use network and ONVIF scanning to identify RTSP-enabled devices and streams.

Capture: Use Python's OpenCV (cv2.VideoCapture) for frame grabbing, or PyAV/FFmpeg for more complex needs.

Security: Be mindful of authentication or access controls on IP cameras—many require valid login credentials.

Troubleshooting: Not all cameras broadcast RTSP or allow open access; you may need to consult camera documentation for the correct stream URL structure.

These steps provide a robust workflow for discovering and capturing RTSP streams of local cameras in Python—ideal for projects in computer vision, surveillance, or automation.
