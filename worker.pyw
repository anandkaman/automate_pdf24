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
from logging.handlers import TimedRotatingFileHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from ocr_processor import process_single_pdf, get_pending_files, get_processed_count, cleanup_processed_inputs
from utils import ensure_folder_exists, LockManager

# Initialize locks
APP_LOCK = LockManager("streamlit_app")
WORKER_LOCK = LockManager("background_worker")

# Settings file (shared with Streamlit app)
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "auto_start.json")
CHECK_INTERVAL = 15  # Check every 15 seconds

# Setup logging with 3-day rotation
log_file = os.path.join(os.path.dirname(__file__), "worker.log")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = TimedRotatingFileHandler(
    log_file,
    when='D',        # Rotate daily
    interval=1,
    backupCount=3,   # Keep 3 days
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)


def load_settings():
    """Load settings from JSON file"""
    defaults = {
        "workers": config.DEFAULT_WORKERS,
        "language": config.OCR_LANGUAGES,
        "deskew": True,
        "delete_input": True
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                return {**defaults, **data}
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
    return defaults


def process_batch(input_folder, output_folder, error_folder, duplicate_folder, settings):
    """Process all pending files"""
    pending = get_pending_files(input_folder, output_folder, duplicate_folder, error_folder)

    if not pending:
        return 0, 0

    logger.info(f"Found {len(pending)} files to process")

    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=settings["workers"]) as executor:
        futures = {
            executor.submit(
                process_single_pdf,
                file_path,
                output_folder,
                settings["language"],
                settings["deskew"],
                True,  # clean (not used)
                settings["delete_input"],
                2,  # max_retries
                error_folder  # move failed files here
            ): file_path
            for file_path in pending
        }

        for future in as_completed(futures):
            file_path = futures[future]
            try:
                result = future.result()
                if result.success:
                    success_count += 1
                    logger.info(f"SUCCESS: {result.file_name}")
                else:
                    fail_count += 1
                    logger.error(f"FAILED: {result.file_name} - {result.error}")
            except Exception as e:
                fail_count += 1
                logger.error(f"ERROR: {os.path.basename(file_path)} - {e}")

    return success_count, fail_count


def main():
    """Main worker loop"""
    logger.info("=" * 50)
    logger.info("PDF24 OCR Background Worker started")
    logger.info(f"Input folder: {config.DEFAULT_INPUT_FOLDER}")
    logger.info(f"Output folder: {config.DEFAULT_OUTPUT_FOLDER}")
    logger.info(f"Error folder: {config.DEFAULT_ERROR_FOLDER}")
    logger.info(f"Duplicate folder: {config.DEFAULT_DUPLICATE_FOLDER}")
    logger.info(f"Check interval: {CHECK_INTERVAL} seconds")
    logger.info("=" * 50)

    # Create folders if they don't exist
    ensure_folder_exists(config.DEFAULT_INPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_OUTPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_ERROR_FOLDER)
    ensure_folder_exists(config.DEFAULT_DUPLICATE_FOLDER)

    # Main loop
    while True:
        try:
            settings = load_settings()

            pending = get_pending_files(
                config.DEFAULT_INPUT_FOLDER,
                config.DEFAULT_OUTPUT_FOLDER,
                config.DEFAULT_DUPLICATE_FOLDER,
                config.DEFAULT_ERROR_FOLDER
            )

            if pending:
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
                    logger.info(f"Processing {len(pending)} files with {settings['workers']} workers...")
                    success, fail = process_batch(
                        config.DEFAULT_INPUT_FOLDER,
                        config.DEFAULT_OUTPUT_FOLDER,
                        config.DEFAULT_ERROR_FOLDER,
                        config.DEFAULT_DUPLICATE_FOLDER,
                        settings
                    )
                    logger.info(f"Batch complete: {success} success, {fail} failed")

                    # Cleanup AFTER batch completes (safe - no race condition)
                    cleaned = cleanup_processed_inputs(
                        config.DEFAULT_INPUT_FOLDER,
                        config.DEFAULT_OUTPUT_FOLDER
                    )
                    if cleaned > 0:
                        logger.info(f"Storage cleanup: removed {cleaned} processed input files")
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


if __name__ == "__main__":
    main()
