# PDF24 Batch OCR Processor

A crash-resistant, parallel OCR processing application for Windows using PDF24's OCR engine.

## Features

- **Parallel Processing**: Utilize multiple CPU cores (configurable workers)
- **Crash Recovery**: Auto-start on boot, resumes where it left off
- **Real-time Progress**: Live updates on remaining/completed files
- **Continuous Mode**: Automatically picks up new files added to input folder
- **Persistent Settings**: All settings saved and restored on restart
- **Log Rotation**: Keeps only 3 days of logs

## Requirements

- Windows 10/11
- Python 3.10+
- [PDF24 Creator](https://www.pdf24.org/en/creator/) (includes pdf24-Ocr.exe)
- Streamlit (`pip install streamlit`)

## Installation

### 1. Install Dependencies

```bash
pip install streamlit
```

### 2. Configure Paths

Edit `config.py` to set your paths:

```python
# PDF24 installation path
OCR_TOOL_PATH = r"C:\Program Files\PDF24\pdf24-Ocr.exe"

# Your input/output folders
DEFAULT_INPUT_FOLDER = r"C:\PDF_Work\Input"
DEFAULT_OUTPUT_FOLDER = r"C:\PDF_Work\Output"
```

## Usage

### Quick Start (Manual)

Double-click `launcher.pyw` or run:

```bash
python launcher.pyw
```

This will:
- Start Streamlit if not already running
- Open browser to http://localhost:8501

### Web Interface

1. Set **Input Folder**: Where your PDFs to process are located
2. Set **Output Folder**: Where OCR'd PDFs will be saved
3. Adjust **Parallel Workers** (recommended: CPU cores - 4)
4. Click **Start Processing**

### Settings (Sidebar)

| Setting | Description |
|---------|-------------|
| Auto-start on boot | Automatically begin processing when app launches |
| Parallel Workers | Number of simultaneous OCR processes |
| OCR Languages | e.g., `eng` or `eng+kan` for English+Kannada |
| Enable Deskew | Straighten tilted pages |
| Delete input after success | Remove original after successful OCR |

All settings are saved to `auto_start.json` and persist across restarts.

## Running as Windows Service (Recommended)

For 24/7 operation and automatic startup:

### Option A: Using NSSM (Recommended)

1. Download [NSSM](https://nssm.cc/download)
2. Extract `nssm.exe` to this folder or add to PATH
3. Run `install_service.bat` as Administrator
4. Select option `[1] Install service`

Service commands:
- Start: `nssm start PDF24_OCR_Processor`
- Stop: `nssm stop PDF24_OCR_Processor`
- Status: `nssm status PDF24_OCR_Processor`
- Remove: `nssm remove PDF24_OCR_Processor`

### Option B: Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Trigger: "When the computer starts"
4. Action: Start a program
   - Program: `pythonw.exe`
   - Arguments: `launcher.pyw`
   - Start in: `D:\Drive_E\projects\ocr control`

## File Structure

```
ocr control/
├── app.py              # Main Streamlit application
├── config.py           # Configuration settings
├── ocr_processor.py    # Core OCR processing logic
├── utils.py            # Utility functions
├── launcher.pyw        # Smart launcher (no console)
├── run.bat             # Simple launcher (with console)
├── install_service.bat # NSSM service installer
├── requirements.txt    # Python dependencies
├── auto_start.json     # Saved settings (auto-generated)
├── ocr_processing.log  # Processing logs (3-day rotation)
└── README.md           # This file
```

## How It Works

1. **Input Monitoring**: Scans input folder for PDF files
2. **Skip Processed**: Files already in output folder are skipped
3. **Parallel OCR**: Processes multiple files simultaneously using PDF24
4. **Instant Save**: Each file is saved immediately after OCR
5. **Delete Original**: Optionally removes input file after success
6. **Continuous Loop**: Keeps checking for new files until stopped

## Crash Recovery

If the app crashes:

1. Already processed files are safe in output folder
2. On restart, it automatically detects remaining files
3. With "Auto-start on boot" enabled, processing resumes automatically

## Troubleshooting

### "PDF24 OCR tool not found"
- Install PDF24 Creator from https://www.pdf24.org/en/creator/
- Verify path in `config.py` matches your installation

### OCR fails silently
- Check `ocr_processing.log` for errors
- Ensure PDF files are not corrupted
- Try with fewer workers (memory issues)

### Service won't start
- Run `install_service.bat` as Administrator
- Check `service_stderr.log` for errors
- Verify Python and Streamlit are installed

### High CPU/Memory usage
- Reduce number of workers in settings
- Large PDFs may require more memory per worker

## Logs

- `ocr_processing.log` - Main processing log (rotates daily, keeps 3 days)
- `service_stdout.log` - Service output (if running as service)
- `service_stderr.log` - Service errors (if running as service)

## License

Free for personal and commercial use.
