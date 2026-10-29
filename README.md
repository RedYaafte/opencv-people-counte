# OpenCV People Counter

Count people entering and leaving an area as they cross a configurable line in a video or camera feed. Use the local web dashboard for uploaded videos, browser camera analysis, SQLite session history, and a live progress chart. The original command-line tool remains available.

## Features

- Person detection with OpenCV's built-in HOG/SVM detector; no model download is required.
- Centroid tracking and directional line-crossing counts.
- On-video direction labels (**ENTRY/EXIT** in the web dashboard, **ENTRADA/SALIDA** in the CLI), track IDs, and color-coded boxes: cyan before a crossing, green after an entry, and red after an exit.
- CLI export of a CSV event log with timestamp, frame number, track ID, and direction.
- A local FastAPI dashboard with uploaded video preview, browser camera processing, session history, and cumulative entries, exits, and occupancy.

## Requirements

- Python 3.10 or newer
- A video file, or a camera connected to the computer running the program

## Web dashboard

Create a virtual environment from the repository root and install the web dependencies:

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-web.txt
```

**Windows (PowerShell):**

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-web.txt
```

Start the local server:

```bash
python -m uvicorn people_counter.web:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Choose a video and set the line orientation, position, and entry direction before selecting **Analyze video**. The annotated preview, counts, and chart update during processing. When complete, you can play or download the annotated MP4. The video limit is 250 MB.

For **Live camera**, grant your browser permission and select **Start camera**. Select **Stop camera** to end the session. Camera processing speed depends on your CPU and video resolution; the app sends the next frame only after the previous frame is analyzed. Browser camera access works on `localhost` and `127.0.0.1`; a remote deployment requires HTTPS and additional security work.

SQLite data and annotated web videos are stored under `data/`, which Git ignores. Uploaded source files are removed after processing. Camera sessions save counts and crossing events, but do not record video. Occupancy is entries minus exits from a starting value of zero, so it can become negative if someone already inside leaves first. This first version is intended for local, single-user use.

## Command-line setup

From the repository root, create a virtual environment and install dependencies.

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Process a video you provide:

```bash
python -m people_counter --source /path/to/your/video.mp4
```

The program writes `outputs/annotated.mp4` and `outputs/events.csv` and prints the final entry and exit counts. The `outputs/` directory is created automatically and is excluded from Git.

To analyze a camera connected to the same computer, run `python -m people_counter --source 0` and press Ctrl+C to stop and save the results. Camera index `0` is usually the first camera. This command does not access a remote visitor's browser camera.

## Configure the counting line

The default line is horizontal at 50% of the frame height. Moving **top to bottom** counts as an entry; moving **bottom to top** counts as an exit. The side labels in the video reflect this configuration.

```bash
python -m people_counter --source /path/to/your/video.mp4 --orientation vertical --line-position 0.6 --entry-direction reverse
```

For a vertical line, `forward` means left to right. `--entry-direction reverse` swaps which direction is counted as an entry. `--line-position` accepts a fraction strictly between 0 and 1. Use `--margin` to change the dead zone around the line, or `--max-distance` and `--max-missed` to tune tracking. Run `python -m people_counter --help` for all options, including custom output paths.

## How it works

1. OpenCV detects people in each frame using a HOG descriptor and SVM classifier.
2. Overlapping detections are reduced, then detections are matched to existing tracks by centroid distance.
3. A crossing is recorded when a tracked center moves from one stable side of the line to the other. The dead zone limits duplicate counts caused by jitter.
4. The event log records each crossing; the annotated video shows the running totals.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Limitations and responsible use

The HOG detector works best when full bodies are visible and the camera is stationary. Overhead views, crowds, occlusions, and poor lighting can reduce accuracy. Centroid tracking may swap IDs when people cross paths. Measure accuracy on your own footage before relying on the counts: manually count entries and exits, then compare them with the CSV. This project does not recognize faces or identify people.

Use footage you have permission to process. Source videos and generated outputs are excluded from Git by default; review any demo media before publishing it.

## License

This project is licensed under the [MIT License](LICENSE).
