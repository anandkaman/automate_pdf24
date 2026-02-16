"""
PDF24 OCR Background Worker
Runs silently, checks for files every minute, processes automatically.
No browser, no terminal - just background processing.

Run with: pythonw worker.pyw
Or set up with NSSM/Task Scheduler
"""
import os
import sys
import time
import json
import logging
import signal
import atexit
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Global flag for graceful shutdown
_shutdown_requested = False

import config
from ocr_processor import process_batch, get_pending_files, get_processed_count
from utils import ensure_folder_exists, LockManager

# Initialize locks
APP_LOCK = LockManager("streamlit_app")
WORKER_LOCK = LockManager("background_worker")

# Settings file (shared with Streamlit app)
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "auto_start.json")
CHECK_INTERVAL = getattr(config, 'POLLING_INTERVAL', 5)  # Check every 5 seconds (default)

# Setup logging with 3-day rotation
log_file = os.path.join(os.path.dirname(__file__), "worker.log")
handler = TimedRotatingFileHandler(
    log_file,
    when='D',        # Rotate daily
    interval=1,
    backupCount=3,   # Keep 3 days
    encoding='utf-8'
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Configure root logger to capture everything (including ocr_processor)
logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global _shutdown_requested
    _shutdown_requested = True
    logger.info(f"Shutdown signal received ({signum}). Finishing current work...")


def cleanup():
    """Cleanup on exit"""
    try:
        WORKER_LOCK.release()
        logger.info("Worker lock released")
    except:
        pass
    logger.info("Worker shutdown complete")


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, 'SIGBREAK'):  # Windows only
    signal.signal(signal.SIGBREAK, signal_handler)

# Register cleanup on exit
atexit.register(cleanup)


def load_settings():
    """Load settings from JSON file"""
    defaults = {
        "auto_start": False,  # Must be enabled to process
        "workers": config.DEFAULT_WORKERS,
        "language": config.OCR_LANGUAGES,
        "deskew": True
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                return {**defaults, **data}
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
    return defaults


def run_batch(input_folder, output_folder, error_folder, duplicate_folder, processing_folder, settings):
    """
    Wrapper for shared process_batch() function.
    Adds logging and shutdown check.
    """
    pending = get_pending_files(input_folder, output_folder, duplicate_folder, error_folder)
    num_files = len(pending) if pending else 0
    logger.info(f"Processing {num_files} files with {settings['workers']} workers...")

    def should_stop():
        return _shutdown_requested

    return process_batch(
        input_folder=input_folder,
        output_folder=output_folder,
        processing_folder=processing_folder,
        error_folder=error_folder,
        duplicate_folder=duplicate_folder,
        language=settings["language"],
        deskew=settings["deskew"],
        num_workers=settings["workers"],
        max_retries=2,
        on_result=None,  # Background worker uses logger, no UI callback needed
        should_stop=should_stop
    )


def main():
    """Main worker loop"""
    logger.info("=" * 50)
    logger.info("PDF24 OCR Background Worker started")
    logger.info(f"Input folder: {config.DEFAULT_INPUT_FOLDER}")
    logger.info(f"Output folder: {config.DEFAULT_OUTPUT_FOLDER}")
    logger.info(f"Processing folder: {config.DEFAULT_PROCESSING_FOLDER}")
    logger.info(f"Error folder: {config.DEFAULT_ERROR_FOLDER}")
    logger.info(f"Duplicate folder: {config.DEFAULT_DUPLICATE_FOLDER}")
    logger.info(f"Check interval: {CHECK_INTERVAL} seconds")
    logger.info("=" * 50)

    # Create folders if they don't exist
    ensure_folder_exists(config.DEFAULT_INPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_OUTPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_PROCESSING_FOLDER)
    ensure_folder_exists(config.DEFAULT_ERROR_FOLDER)
    ensure_folder_exists(config.DEFAULT_DUPLICATE_FOLDER)

    # Main loop
    while not _shutdown_requested:
        try:
            settings = load_settings()

            # Check if auto_start is enabled - if not, skip processing
            if not settings.get("auto_start", False):
                time.sleep(CHECK_INTERVAL)
                continue

            # Quick check: any PDFs in Input or Processing folder?
            has_work = False
            for folder in [config.DEFAULT_INPUT_FOLDER, config.DEFAULT_PROCESSING_FOLDER]:
                if os.path.exists(folder):
                    if any(f.lower().endswith('.pdf') for f in os.listdir(folder)):
                        has_work = True
                        break

            if has_work:
                # Check for App conflict
                if APP_LOCK.is_locked():
                    logger.warning("Streamlit App is currently processing. Skipping background worker loop to avoid conflict.")
                    time.sleep(CHECK_INTERVAL)
                    continue

                # Acquire worker lock
                if not WORKER_LOCK.acquire():
                    logger.debug("Another worker instance is active. Skipping.")
                    time.sleep(CHECK_INTERVAL)
                    continue

                try:
                    logger.info(f"Starting batch with {settings['workers']} workers...")
                    success, fail = run_batch(
                        config.DEFAULT_INPUT_FOLDER,
                        config.DEFAULT_OUTPUT_FOLDER,
                        config.DEFAULT_ERROR_FOLDER,
                        config.DEFAULT_DUPLICATE_FOLDER,
                        config.DEFAULT_PROCESSING_FOLDER,
                        settings
                    )
                    logger.info(f"Batch complete: {success} success, {fail} failed")
                finally:
                    WORKER_LOCK.release()

            # Wait before next check
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}")
            time.sleep(CHECK_INTERVAL)

    logger.info("Worker exiting gracefully")


if __name__ == "__main__":
    main()
