import cv2
import numpy as np

class Display:
    def __init__(self, window_name="Remote Desktop"):
        self.window_name = window_name
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        
    def show_frame(self, frame_bgr: np.ndarray):
        cv2.imshow(self.window_name, frame_bgr)
        
    def close(self):
        cv2.destroyWindow(self.window_name)
