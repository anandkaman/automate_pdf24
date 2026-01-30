================================================================================
                      PDF24 BATCH OCR PROCESSOR
================================================================================

A crash-resistant, parallel OCR processing application for Windows
using PDF24's OCR engine.


FEATURES
--------
- Parallel Processing: Utilize multiple CPU cores
- Crash Recovery: Auto-start on boot, resumes where it left off
- Real-time Progress: Live updates on remaining/completed files
- Continuous Mode: Automatically picks up new files
- Persistent Settings: All settings saved and restored
- Log Rotation: Keeps only 3 days of logs


REQUIREMENTS
------------
- Windows 10/11
- Python 3.10+
- PDF24 Creator (https://www.pdf24.org/en/creator/)
- Streamlit (pip install streamlit)


QUICK START
-----------
1. Install Streamlit:
   pip install streamlit

2. Double-click: launcher.pyw
   OR run: python launcher.pyw

3. Browser opens to http://localhost:8501

4. Set your input/output folders and click "Start Processing"


CONFIGURATION
-------------
Edit config.py to change default settings:

  OCR_TOOL_PATH = Path to pdf24-Ocr.exe
  DEFAULT_INPUT_FOLDER = Where your PDFs are
  DEFAULT_OUTPUT_FOLDER = Where to save OCR'd PDFs
  OCR_LANGUAGES = OCR language(s), e.g., "eng+kan"


SETTINGS (in Web UI sidebar)
----------------------------
  Auto-start on boot    - Begin processing when app launches
  Parallel Workers      - Number of simultaneous OCR processes
  OCR Languages         - e.g., "eng" or "eng+kan"
  Enable Deskew         - Straighten tilted pages
  Delete input          - Remove original after success

Settings are saved to auto_start.json automatically.


RUNNING AS WINDOWS SERVICE (Recommended for 24/7)
------------------------------------------------

Step 1: Download NSSM
  - Go to: https://nssm.cc/download
  - Download: nssm-2.24.zip (or latest)

Step 2: Extract and place nssm.exe
  - Extract the downloaded zip file
  - Open extracted folder -> go to "win64" folder
  - Copy "nssm.exe" to your project folder:
    D:\Drive_E\projects\ocr control\nssm.exe

Step 3: Install the service
  - Right-click "install_service.bat" -> Run as administrator
  - Select [1] Install service
  - Done! Service starts automatically on boot

Service will:
  - Start automatically on Windows boot
  - Restart automatically if it crashes
  - Run in background (no window)

Access web UI anytime at: http://localhost:8501

Service commands (run as admin):
  nssm start PDF24_OCR_Processor
  nssm stop PDF24_OCR_Processor
  nssm status PDF24_OCR_Processor
  nssm remove PDF24_OCR_Processor


FILE STRUCTURE
--------------
  app.py              - Main Streamlit application
  config.py           - Configuration settings
  ocr_processor.py    - Core OCR processing logic
  utils.py            - Utility functions
  launcher.pyw        - Smart launcher (no console window)
  run.bat             - Simple launcher (shows console)
  install_service.bat - NSSM service installer
  requirements.txt    - Python dependencies
  auto_start.json     - Saved settings (auto-created)
  ocr_processing.log  - Processing logs


HOW IT WORKS
------------
1. Scans input folder for PDF files
2. Skips files already in output folder
3. Processes multiple files in parallel using PDF24
4. Saves each file immediately after OCR
5. Optionally deletes input file after success
6. Keeps checking for new files until stopped


CRASH RECOVERY
--------------
If app crashes:
- Processed files are safe in output folder
- On restart, detects remaining files automatically
- With "Auto-start on boot", processing resumes automatically


TROUBLESHOOTING
---------------
"PDF24 OCR tool not found"
  -> Install PDF24 Creator
  -> Check path in config.py

OCR fails silently
  -> Check ocr_processing.log
  -> Try fewer workers

Service won't start
  -> Run as Administrator
  -> Check service_stderr.log

High CPU/Memory
  -> Reduce workers in settings


LOGS
----
  ocr_processing.log  - Main log (3-day rotation)
  service_stdout.log  - Service output
  service_stderr.log  - Service errors


================================================================================
                           Free for personal and commercial use
================================================================================
