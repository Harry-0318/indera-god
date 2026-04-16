# Camera Color Detection Setup

Color detection is now done by the webcam through `cv.py` and the Flask backend.

## What changed

- Arduino 1 no longer reads the TCS34725
- The backend opens camera `0`
- `cv.py` detects the dominant color inside the center ROI
- The UI shows:
  - detected color
  - detected contour area

## How it works

- `cv.py` contains HSV ranges for:
  - Red
  - Green
  - Blue
  - Yellow
  - Black
  - White
- The backend continuously reads frames from the webcam
- It runs `detect_color(frame)`
- The result is persisted into runtime state and shown in the dashboard

## Requirements

Install OpenCV:

```bash
pip install opencv-python
```

## Test the camera detector directly

You can run:

```bash
python cv.py
```

This opens a preview window and shows the detected color over the ROI.

## Use it in the web app

Start the app normally:

```bash
python app.py
```

The backend will start a camera color thread automatically.

## Notes

- Camera index is currently `0` in `app.py`
- If your webcam is on another index, change:

```python
CAMERA_INDEX = 0
```

- The raw color sensor path was removed from Arduino 1 to keep firmware minimal
