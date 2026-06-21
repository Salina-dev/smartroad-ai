# SmartRoad AI - Road Damage Detection Platform

A professional-level road monitoring system built with Python, Streamlit, YOLOv8, OpenCV, SQLite, Plotly, Folium, and ReportLab.

## Features

- User authentication with login and registration
- Modern dashboard with dark-theme style
- Upload image and video for damage detection
- Live camera inspection support
- GPS and location tracking with map visualization
- Detection history and analytic dashboards
- Automated PDF and Excel report generation
- Intelligent repair recommendations
- SQLite database storage for users, detections, locations, and reports

## Setup

1. Create a Python virtual environment

```bash
python -m venv .venv
.\.venv\Scripts\activate
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Place a YOLOv8 model file in the workspace root

- `yolov8n.pt` or your own custom weights file

4. Start the app

```bash
streamlit run app.py
```

## Usage

- Register a new user, then login
- Use the sidebar to switch between dashboard features
- Upload images or videos for automated detection
- Save detection results to history and generate reports
- Configure camera stream URL for live inspection

## Notes

- The model loader expects `yolov8n.pt` by default. Change the path from the Settings page if needed.
- If the YOLOv8 weights file is not available, detection pages will display a warning and allow record keeping once configured.

## File Structure

- `app.py` - Streamlit frontend and application logic
- `db.py` - SQLite database layer
- `detector.py` - YOLOv8 detection integration
- `report_generator.py` - PDF and Excel report creation
- `requirements.txt` - Python dependencies

## Recommended Improvements

- Add multi-user roles and audit logging
- Integrate RTSP camera authentication for CCTV streams
- Replace placeholder analytics with richer spatial insights
- Train a custom YOLOv8 model for highest road damage accuracy
