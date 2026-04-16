import cv2
import numpy as np


COLOR_RANGES = {
    "Red": [
        (np.array([0, 120, 70]), np.array([10, 255, 255])),
        (np.array([170, 120, 70]), np.array([180, 255, 255])),
    ],
    "Green": [
        (np.array([35, 50, 50]), np.array([85, 255, 255])),
    ]
}


def roi_bounds(width, height):
    return (
        int(width * 0.3),
        int(height * 0.3),
        int(width * 0.7),
        int(height * 0.7),
    )


def detect_color(frame, min_area=1000):
    frame = cv2.flip(frame, 1)
    height, width, _ = frame.shape
    x1, y1, x2, y2 = roi_bounds(width, height)
    roi = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    best_color = "UNKNOWN"
    best_area = 0

    for color_name, ranges in COLOR_RANGES.items():
        combined_mask = None

        for lower, upper in ranges:
            mask = cv2.inRange(hsv, lower, upper)
            combined_mask = mask if combined_mask is None else cv2.add(combined_mask, mask)

        contours, _ = cv2.findContours(
            combined_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        for contour in contours:
            area = cv2.contourArea(contour)
            if area > max(min_area, best_area):
                best_area = int(area)
                best_color = color_name.upper()

    return {
        "color_name": best_color,
        "area": best_area,
        "roi": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
    }
