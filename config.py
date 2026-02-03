"""
Configuration settings for PDF24 OCR Batch Processor
"""
from pathlib import Path

# PDF24 OCR Tool Path (use pdf24-Ocr.exe, NOT DocTool)
OCR_TOOL_PATH = r"C:\Program Files\PDF24\pdf24-Ocr.exe"

# Default folders
DEFAULT_INPUT_FOLDER = r"C:\PDF_Work\Input"
DEFAULT_OUTPUT_FOLDER = r"C:\PDF_Work\Output"
DEFAULT_ERROR_FOLDER = r"C:\PDF_Work\Error"
DEFAULT_DUPLICATE_FOLDER = r"C:\PDF_Work\Duplicate"
DEFAULT_PROCESSING_FOLDER = r"C:\PDF_Work\Processing"  # Temp folder during OCR

# OCR Settings
OCR_LANGUAGES = "eng+kan"  # English + Kannada
OCR_DPI = 300              # DPI for processing
OCR_DESKEW = True          # Correct skewed pages
OCR_REMOVE_BACKGROUND = False  # Remove page background

# Worker settings
MIN_WORKERS = 1
MAX_WORKERS = 22          
DEFAULT_WORKERS = 3

# File settings
SUPPORTED_EXTENSIONS = [".pdf"]

# State file to track progress (for crash recovery)
STATE_FILE = "processing_state.json"
