"""
PDF24 Batch OCR Processor - Streamlit Application
Crash-resistant parallel OCR processing for Windows
"""
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import os
from datetime import datetime
import time
import json

import config
from ocr_processor import (
    validate_ocr_tool,
    process_batch,
    get_pending_files,
    get_processed_count
)
from utils import (
    ensure_folder_exists,
    format_time,
    estimate_remaining_time,
    SessionState,
    get_system_info,
    get_folder_stats,
    LockManager
)

# Initialize locks
APP_LOCK = LockManager("streamlit_app")
WORKER_LOCK = LockManager("background_worker")

# Page configuration
st.set_page_config(
    page_title="PDF24 Batch OCR",
    page_icon="📄",
    layout="wide"
)

# Auto-start config file
AUTO_START_FILE = "auto_start.json"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_LOG_FILE = os.path.join(PROJECT_DIR, "worker.log")


def read_worker_log_tail(n=20):
    """Read last N lines from worker.log"""
    try:
        if not os.path.exists(WORKER_LOG_FILE):
            return "No worker log found."
        with open(WORKER_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return "".join(lines[-n:]) if lines else "Worker log is empty."
    except Exception as e:
        return f"Could not read worker log: {e}"


def load_settings():
    """Load all settings from file"""
    defaults = {
        "auto_start": False,
        "workers": config.DEFAULT_WORKERS,
        "language": config.OCR_LANGUAGES,
        "deskew": True
    }
    try:
        if os.path.exists(AUTO_START_FILE):
            with open(AUTO_START_FILE, 'r') as f:
                data = json.load(f)
                return {**defaults, **data}
    except:
        pass
    return defaults


def save_settings(settings: dict):
    """Save all settings to file"""
    try:
        with open(AUTO_START_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except:
        pass


# Initialize session state
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'results' not in st.session_state:
    st.session_state.results = []
if 'stop_requested' not in st.session_state:
    st.session_state.stop_requested = False
if 'auto_started' not in st.session_state:
    st.session_state.auto_started = False


def run_processing(input_folder, output_folder, error_folder, num_workers, language, deskew):
    """
    Main processing loop using shared process_batch function.
    Uses callbacks for UI updates while the core logic is shared with worker.pyw.
    """
    ensure_folder_exists(output_folder)
    ensure_folder_exists(error_folder)
    ensure_folder_exists(config.DEFAULT_PROCESSING_FOLDER)

    state = SessionState()
    progress_bar = st.progress(0)
    status_container = st.container()
    results_container = st.container()

    start_time = datetime.now()
    total_success = 0
    total_fail = 0
    batch_processed = 0
    batch_size = 0
    log_messages = []

    with status_container:
        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
        metric_remaining = col_s1.empty()
        metric_completed = col_s2.empty()
        metric_success = col_s3.empty()
        metric_failed = col_s4.empty()
        metric_eta = col_s5.empty()

    current_file_display = st.empty()
    log_display = results_container.empty()

    # Check for worker conflict
    if WORKER_LOCK.is_locked():
        st.error("⚠️ Background Worker is already running! Please stop it before starting GUI processing to avoid conflicts.")
        st.session_state.processing = False
        return

    # Acquire app lock
    if not APP_LOCK.acquire():
        st.error("⚠️ Another instance of the App is already processing!")
        st.session_state.processing = False
        return

    def on_result(result):
        """Callback for UI updates when a file is processed"""
        nonlocal total_success, total_fail, batch_processed, log_messages

        batch_processed += 1

        if result.success:
            total_success += 1
            state.mark_processed(result.file_name, True)
            log_msg = f"✅ {result.file_name} ({format_time(result.processing_time)})"
        else:
            total_fail += 1
            state.mark_processed(result.file_name, False)
            log_msg = f"❌ {result.file_name}: {result.error}"

        log_messages.append(log_msg)

        # Prevent memory leak
        if len(log_messages) > 100:
            log_messages = log_messages[-100:]

        # Update UI
        elapsed = (datetime.now() - start_time).total_seconds()
        progress = min(batch_processed / max(batch_size, 1), 1.0)

        progress_bar.progress(progress)
        current_file_display.text(f"Processed: {result.file_name}")

        # Real-time folder counts
        remaining = len(get_pending_files(input_folder, output_folder, config.DEFAULT_DUPLICATE_FOLDER, config.DEFAULT_ERROR_FOLDER))
        completed = get_processed_count(output_folder)

        metric_remaining.metric("Remaining", remaining)
        metric_completed.metric("Completed", completed)
        metric_success.metric("Success", total_success)
        metric_failed.metric("Failed", total_fail)
        metric_eta.metric("ETA", estimate_remaining_time(batch_processed, batch_size, elapsed))

        log_display.text("\n".join(log_messages[-15:]))

    def should_stop():
        """Callback to check if processing should stop"""
        return st.session_state.stop_requested

    try:
        # Continuous processing loop
        while not st.session_state.stop_requested:
            # Get current pending files count
            pending_files = get_pending_files(input_folder, output_folder, config.DEFAULT_DUPLICATE_FOLDER, config.DEFAULT_ERROR_FOLDER)

            # Also check Processing folder for files
            processing_files = []
            if os.path.exists(config.DEFAULT_PROCESSING_FOLDER):
                processing_files = [f for f in os.listdir(config.DEFAULT_PROCESSING_FOLDER) if f.lower().endswith('.pdf')]

            if not pending_files and not processing_files:
                # No files to process, wait and check again
                current_file_display.text("Waiting for new files...")
                time.sleep(2)

                # Update stats
                remaining = len(get_pending_files(input_folder, output_folder, config.DEFAULT_DUPLICATE_FOLDER, config.DEFAULT_ERROR_FOLDER))
                completed = get_processed_count(output_folder)
                metric_remaining.metric("Remaining", remaining)
                metric_completed.metric("Completed", completed)
                continue

            # Reset batch counters for new batch
            batch_size = len(pending_files) + len(processing_files)
            batch_processed = 0
            state.start_session(input_folder, output_folder, batch_size)

            # Use shared process_batch function
            success, fail = process_batch(
                input_folder=input_folder,
                output_folder=output_folder,
                processing_folder=config.DEFAULT_PROCESSING_FOLDER,
                error_folder=error_folder,
                duplicate_folder=config.DEFAULT_DUPLICATE_FOLDER,
                language=language,
                deskew=deskew,
                num_workers=num_workers,
                max_retries=2,
                on_result=on_result,
                should_stop=should_stop
            )

            # Batch complete
            progress_bar.progress(1.0)
            current_file_display.text("Batch complete. Checking for new files...")
            time.sleep(1)
    finally:
        APP_LOCK.release()


def main():
    st.title("PDF24 Batch OCR Processor")
    st.caption("Crash-resistant parallel OCR processing for Windows")

    # Create default folders if they don't exist
    ensure_folder_exists(config.DEFAULT_INPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_OUTPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_PROCESSING_FOLDER)
    ensure_folder_exists(config.DEFAULT_ERROR_FOLDER)
    ensure_folder_exists(config.DEFAULT_DUPLICATE_FOLDER)

    # Check PDF24 installation
    if not validate_ocr_tool():
        st.error(f"PDF24 OCR tool not found at: {config.OCR_TOOL_PATH}")
        st.info("Please install PDF24 or update the path in config.py")
        return

    st.success("PDF24 OCR tool found")

    sys_info = get_system_info()
    saved_settings = load_settings()

    # Sidebar for settings
    with st.sidebar:
        st.header("Settings")

        # Auto-start toggle (persisted to file)
        auto_start = st.toggle(
            "Auto-start on boot",
            value=saved_settings["auto_start"],
            help="Automatically start processing when app launches (useful for crash recovery)"
        )

        st.divider()

        num_workers = st.slider(
            "Parallel Workers",
            min_value=config.MIN_WORKERS,
            max_value=config.MAX_WORKERS,
            value=saved_settings["workers"],
            help=f"Your system has {sys_info['cpu_count']} CPU cores"
        )

        st.divider()
        st.subheader("OCR Options")

        language = st.text_input(
            "OCR Languages",
            value=saved_settings["language"],
            help="e.g., 'eng' for English, 'eng+kan' for English+Kannada"
        )

        deskew = st.checkbox("Enable Deskew", value=saved_settings["deskew"])

        # Save all settings when changed
        save_settings({
            "auto_start": auto_start,
            "workers": num_workers,
            "language": language,
            "deskew": deskew
        })

    # Main content - Folder selection
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Input Folder")
        input_folder = st.text_input(
            "Path to PDFs to process",
            value=config.DEFAULT_INPUT_FOLDER,
            key="input_folder"
        )
        if not os.path.exists(input_folder):
            st.warning("Folder does not exist")

    with col2:
        st.subheader("Output Folder")
        output_folder = st.text_input(
            "Path to save OCR'd PDFs",
            value=config.DEFAULT_OUTPUT_FOLDER,
            key="output_folder"
        )

    st.divider()

    pending_files = get_pending_files(input_folder, output_folder, config.DEFAULT_DUPLICATE_FOLDER, config.DEFAULT_ERROR_FOLDER)
    worker_active = WORKER_LOCK.is_locked()

    # Show folder stats
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    input_stats = get_folder_stats(input_folder)
    output_stats = get_folder_stats(output_folder)
    error_stats = get_folder_stats(config.DEFAULT_ERROR_FOLDER)
    processing_stats = get_folder_stats(config.DEFAULT_PROCESSING_FOLDER)

    col_f1.metric("Input", input_stats["count"])
    col_f2.metric("Output", output_stats["count"])
    col_f3.metric("Processing", processing_stats["count"])
    col_f4.metric("Errors", error_stats["count"])

    if worker_active:
        # Background worker is running - show status, act as config panel
        st.info("Background Worker is active (PID: {}). Settings changes are applied on next batch.".format(
            WORKER_LOCK.get_owner_pid()
        ))

        # Show worker log
        st.subheader("Worker Log (live)")
        st.code(read_worker_log_tail(20), language="log")

        # Auto-refresh every 10 seconds to show live status
        st_autorefresh(interval=10000, key="worker_status_refresh")
    else:
        # No background worker - show start/stop buttons for GUI processing
        col_btn1, col_btn2 = st.columns([1, 1])

        with col_btn1:
            start_button = st.button(
                "Start Processing",
                type="primary",
                disabled=st.session_state.processing,
                use_container_width=True
            )

        with col_btn2:
            stop_button = st.button(
                "Stop Processing",
                disabled=not st.session_state.processing,
                use_container_width=True
            )

        if stop_button:
            st.session_state.stop_requested = True
            st.warning("Stop requested - waiting for current files to complete...")

        # Auto-start logic - starts whenever files are pending and auto_start is enabled
        should_auto_start = (
            auto_start and
            not st.session_state.processing and
            len(pending_files) > 0
        )

        if start_button or should_auto_start:
            if should_auto_start:
                st.info("Auto-starting processing...")

            st.session_state.processing = True
            st.session_state.stop_requested = False

            run_processing(
                input_folder, output_folder, config.DEFAULT_ERROR_FOLDER,
                num_workers, language, deskew
            )

        # Auto-refresh page every 30 seconds when idle (to detect new files)
        if auto_start and not st.session_state.processing:
            st_autorefresh(interval=30000, key="auto_refresh")  # 30 seconds


if __name__ == "__main__":
    main()
