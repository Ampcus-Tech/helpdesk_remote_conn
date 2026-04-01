import mss
import cv2
import numpy as np
import time
import platform
import sys
from av import VideoFrame
from aiortc import VideoStreamTrack

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import TARGET_FPS, DEFAULT_QUALITY, QUALITY_SETTINGS
from common.config import CAPTURE_MAX_WIDTH, CAPTURE_MAX_HEIGHT

class ScreenCaptureTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, fps=TARGET_FPS, scale: float | None = None):
        super().__init__()
        self.fps = fps
        if scale is None:
            scale = QUALITY_SETTINGS.get(DEFAULT_QUALITY, {}).get("scale", 1.0)
        self.scale = float(scale)
        
        # Check macOS permissions
        if platform.system() == "Darwin":
            try:
                self.sct = mss.mss()
                self.monitor = self.sct.monitors[1]  # primary monitor
                # Test screen capture permission
                test_capture = self.sct.grab(self.monitor)
            except Exception as e:
                raise PermissionError(
                    "macOS Screen Recording permission required.\n"
                    "Go to System Settings → Privacy & Security → Screen Recording\n"
                    "and enable for your terminal application."
                )
        else:
            self.sct = mss.mss()
            self.monitor = self.sct.monitors[1]  # primary monitor
            
        self.last_capture_time = 0
        self._interval = 1.0 / self.fps
        self._next_capture_at = time.perf_counter()

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        
        now = time.perf_counter()
        wait = self._next_capture_at - now
        if wait > 0:
            import asyncio
            await asyncio.sleep(wait)
            
        sct_img = self.sct.grab(self.monitor)
        self.last_capture_time = time.time()
        self._next_capture_at += self._interval
        late_by = time.perf_counter() - self._next_capture_at
        if late_by > self._interval:
            # If capture/encode falls behind, resync schedule to prevent drift buildup.
            self._next_capture_at = time.perf_counter() + self._interval
        
        # Convert mss image to numpy array (BGRA)
        img = np.asarray(sct_img)

        h, w = img.shape[:2]
        auto_scale = 1.0
        if CAPTURE_MAX_WIDTH > 0 and w > CAPTURE_MAX_WIDTH:
            auto_scale = min(auto_scale, CAPTURE_MAX_WIDTH / w)
        if CAPTURE_MAX_HEIGHT > 0 and h > CAPTURE_MAX_HEIGHT:
            auto_scale = min(auto_scale, CAPTURE_MAX_HEIGHT / h)
        effective_scale = min(self.scale, auto_scale)

        # Keep a fast-path when no resize is needed, but always emit BGR24.
        # On Windows, BGRA alpha can introduce compositor artifacts (black/overlap)
        # during app/window transitions for some capture/encode pipelines.
        if effective_scale >= 0.999:
            bgr = img[:, :, :3]
            frame = VideoFrame.from_ndarray(bgr, format="bgr24")
            frame.pts = pts
            frame.time_base = time_base
            return frame

        width = int(w * effective_scale)
        height = int(h * effective_scale)
        resized = cv2.resize(img, (width, height), interpolation=cv2.INTER_LINEAR)
        bgr = resized[:, :, :3]
        
        # Create VideoFrame
        frame = VideoFrame.from_ndarray(bgr, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame
