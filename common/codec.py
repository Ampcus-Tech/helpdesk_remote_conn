import cv2
import numpy as np
from typing import Tuple, Optional

def resize_frame(frame: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return frame
    width = int(frame.shape[1] * scale)
    height = int(frame.shape[0] * scale)
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

def encode_frame_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    ret, encoded = cv2.imencode('.jpg', frame, encode_param)
    return encoded.tobytes()

def decode_frame_jpeg(frame_bytes: bytes) -> np.ndarray:
    nparr = np.frombuffer(frame_bytes, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

def compute_dirty_rects(current_frame: np.ndarray, previous_frame: np.ndarray, threshold: int = 30) -> Optional[np.ndarray]:
    if previous_frame is None:
        return current_frame

    # Create mask of differences
    diff = cv2.absdiff(current_frame, previous_frame)
    gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_diff, threshold, 255, cv2.THRESH_BINARY)
    
    # We could find bounding boxes to only send those, but for aiortc video track, 
    # sending a full frame is standard because the underlying hardware encoder (H264/VP8) 
    # handles motion estimation and differential coding far more efficiently than Python dirty rects.
    # Therefore, we will mostly return the frame directly to aiortc, 
    # but we can use this function if we were strictly sending via data channel.
    return current_frame
