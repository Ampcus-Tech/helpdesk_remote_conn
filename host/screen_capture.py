import mss
import cv2
import numpy as np
import time
from av import VideoFrame
from aiortc import VideoStreamTrack

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import TARGET_FPS, DEFAULT_QUALITY, QUALITY_SETTINGS

class ScreenCaptureTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, fps=TARGET_FPS, scale: float | None = None):
        super().__init__()
        self.fps = fps
        if scale is None:
            scale = QUALITY_SETTINGS.get(DEFAULT_QUALITY, {}).get("scale", 1.0)
        self.scale = float(scale)
        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]  # primary monitor
        self.last_capture_time = 0
        self._interval = 1.0 / self.fps

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        
        now = time.time()
        elapsed = now - self.last_capture_time
        if elapsed < self._interval:
            import asyncio
            await asyncio.sleep(self._interval - elapsed)
            
        sct_img = self.sct.grab(self.monitor)
        self.last_capture_time = time.time()
        
        # Convert mss image to numpy array (BGRA)
        img = np.array(sct_img)
        # Convert to BGR
        img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        if self.scale != 1.0:
            width = int(img_bgr.shape[1] * self.scale)
            height = int(img_bgr.shape[0] * self.scale)
            img_bgr = cv2.resize(img_bgr, (width, height), interpolation=cv2.INTER_AREA)
        
        # Create VideoFrame
        frame = VideoFrame.from_ndarray(img_bgr, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame
