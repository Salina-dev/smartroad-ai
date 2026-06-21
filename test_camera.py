import cv2

cap = cv2.VideoCapture(0)

print("Camera opened:", cap.isOpened())

while True:
    ret, frame = cap.read()

    if not ret:
        print("No frame received")
        break

    cv2.imshow("Camera Test", frame)

    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()