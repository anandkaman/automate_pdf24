# PDF24 Batch OCR Processor

A crash-resistant, parallel OCR processing application for Windows using PDF24's OCR engine.

## Features

- **Parallel Processing**: Utilize multiple CPU cores (configurable workers)
- **Crash Recovery**: Auto-restarts on failure, resumes where it left off
- **Background Service**: Runs 24/7 without browser or terminal
- **Error Handling**: Failed files moved to Error folder (no infinite retries)
- **Retry Logic**: Retries failed files up to 2 times before giving up
- **Persistent Settings**: All settings saved to JSON
- **Log Rotation**: Keeps only 3 days of logs

## Requirements

- Windows 10/11
- Python 3.10+ (with "Add to PATH" enabled)
- [PDF24 Creator](https://www.pdf24.org/en/creator/) (includes pdf24-Ocr.exe)

## Quick Setup

### Step 1: Install Python Dependencies

```bash
pip install streamlit streamlit-autorefresh
```

### Step 2: Configure Settings

1. Double-click `run.bat` to open the web UI
2. Configure your settings in the sidebar:
   - **Parallel Workers**: Number of simultaneous OCR processes (recommended: CPU cores - 4)
   - **OCR Languages**: e.g., `eng` or `eng+kan` for English+Kannada
   - **Enable Deskew**: Straighten tilted pages
   - **Delete input after success**: Remove original after successful OCR
3. Close the browser when done (settings are auto-saved)

### Step 3: Install Background Service

1. Right-click `install_task.bat` → **Run as administrator**
2. Select option `[1] Install background worker`
3. Done! Worker will:
   - Start automatically on Windows boot
   - Restart automatically if it crashes
   - Check for new files every 60 seconds

## Folder Structure

```
C:\PDF_Work\
├── Input\    ← Place PDFs here to process
├── Output\   ← Successfully processed files appear here
└── Error\    ← Failed files (after 2 retries) are moved here
```

Folders are created automatically on first run.

## Usage

### Background Worker (Recommended)

After installing with `install_task.bat`, the worker runs silently in the background:
- No browser needed
- No terminal window
- Checks for files every 60 seconds
- Logs to `worker.log`

### Web UI (For Settings/Monitoring)

Double-click `run.bat` to:
- View processing progress
- Change settings (workers, language, etc.)
- Monitor remaining/completed files

Both can run simultaneously - the UI is for monitoring, the worker does the actual processing.

### Task Scheduler Commands

Use `install_task.bat` menu:

| Option | Action |
|--------|--------|
| 1 | Install background worker |
| 2 | Uninstall task |
| 3 | Start task now |
| 4 | Stop task |
| 5 | Check status |

## Configuration

### config.py

Edit `config.py` to change default paths:

```python
# PDF24 installation path
OCR_TOOL_PATH = r"C:\Program Files\PDF24\pdf24-Ocr.exe"

# Default folders
DEFAULT_INPUT_FOLDER = r"C:\PDF_Work\Input"
DEFAULT_OUTPUT_FOLDER = r"C:\PDF_Work\Output"
DEFAULT_ERROR_FOLDER = r"C:\PDF_Work\Error"

# Worker settings
DEFAULT_WORKERS = 10
MAX_WORKERS = 22
```

### auto_start.json

Runtime settings (managed via Web UI):

```json
{
  "workers": 4,
  "language": "eng+kan",
  "deskew": true,
  "delete_input": true
}
```

## File Structure

```
ocr control/
├── app.py              # Streamlit web UI
├── config.py           # Default configuration
├── ocr_processor.py    # Core OCR processing logic
├── utils.py            # Utility functions
├── worker.pyw          # Background worker (no console)
├── run.bat             # Launch web UI
├── install_task.bat    # Task Scheduler installer
├── requirements.txt    # Python dependencies
├── auto_start.json     # User settings (auto-generated)
├── worker.log          # Processing logs (3-day rotation)
└── README.md           # This file
```

## How It Works

1. **Input Monitoring**: Worker checks input folder every 60 seconds
2. **Skip Processed**: Files already in output folder are skipped
3. **Parallel OCR**: Processes multiple files simultaneously using PDF24
4. **Retry on Failure**: Failed files retry up to 2 times
5. **Error Handling**: After 2 failures, file moves to Error folder
6. **Instant Save**: Each file saved immediately after OCR
7. **Delete Original**: Optionally removes input file after success

## Crash Recovery

The system is designed to survive crashes:

- **Windows crash**: Task Scheduler restarts worker on boot
- **Worker crash**: Auto-restarts within 1 minute
- **PDF24 crash**: Process killed, file retried automatically
- **Partial files**: Cleaned up automatically on retry

Already processed files are always safe in the Output folder.

## Troubleshooting

### "Python not found" during install

- Download Python from https://www.python.org/downloads/
- During installation, check **"Add Python to PATH"**
- Restart computer and try again

### "PDF24 OCR tool not found"

- Install PDF24 Creator from https://www.pdf24.org/en/creator/
- Verify path in `config.py` matches your installation

### Files not processing

1. Check `worker.log` for errors
2. Verify worker is running: `install_task.bat` → Option 5
3. Check if files are in Error folder (failed permanently)

### High CPU/Memory usage

- Reduce number of workers in Web UI settings
- Large PDFs require more memory per worker

### Worker not starting on boot

- Run `install_task.bat` as **Administrator**
- Select Option 2 (Uninstall), then Option 1 (Install) again

## Logs

- `worker.log` - Processing log (rotates daily, keeps 3 days)

View recent logs:
```bash
type worker.log
```

## Transferring to Another Computer

1. Copy the entire project folder
2. Install Python (with "Add to PATH" checked)
3. Install PDF24 Creator
4. Run `pip install streamlit streamlit-autorefresh`
5. Run `install_task.bat` as administrator → Option 1

The installer automatically detects Python location on each system.

## License

Free for personal and commercial use.
