import cv2

from cv_detector import detect_color


def preview_camera(camera_index=0):
    cap = cv2.VideoCapture(camera_index)

    while True:
        ret, frame = cap.read()
        if not ret:
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
            f"{result['color_name']} ({result['area']})",
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        cv2.imshow("Color Detection", preview)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    preview_camera()
