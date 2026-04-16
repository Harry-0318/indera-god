import cv2

from cv_detector import detect_color


CAMERA_INDEX = 0


def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print(f"Failed to open camera index {CAMERA_INDEX}")
        return

    print("Camera test started. Press ESC to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Camera read failed.")
            break

        result = detect_color(frame)
        preview = cv2.flip(frame, 1)

        x1 = result["roi"]["x1"]
        y1 = result["roi"]["y1"]
        x2 = result["roi"]["x2"]
        y2 = result["roi"]["y2"]

        cv2.rectangle(preview, (x1, y1), (x2, y2), (255, 0, 0), 2)
        cv2.putText(
            preview,
            f"Color: {result['color_name']}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            preview,
            f"Area: {result['area']}",
            (20, 75),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            preview,
            "ESC to quit",
            (20, preview.shape[0] - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (200, 200, 200),
            2,
        )

        cv2.imshow("Indera Camera Test", preview)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
