"""
PDF24 Batch OCR Processor - Streamlit Application
Crash-resistant parallel OCR processing for Windows
"""
import streamlit as st
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time
import json

import config
from ocr_processor import (
    validate_ocr_tool,
    process_single_pdf,
    get_pending_files,
    get_processed_count
)
from utils import (
    ensure_folder_exists,
    format_time,
    estimate_remaining_time,
    SessionState,
    get_system_info
)

# Page configuration
st.set_page_config(
    page_title="PDF24 Batch OCR",
    page_icon="📄",
    layout="wide"
)

# Auto-start config file
AUTO_START_FILE = "auto_start.json"


def load_settings():
    """Load all settings from file"""
    defaults = {
        "auto_start": False,
        "workers": config.DEFAULT_WORKERS,
        "language": config.OCR_LANGUAGES,
        "deskew": True,
        "delete_input": True
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


def run_processing(input_folder, output_folder, num_workers, language, deskew, delete_input):
    """Main processing loop"""
    ensure_folder_exists(output_folder)

    state = SessionState()
    progress_bar = st.progress(0)
    status_container = st.container()
    results_container = st.container()

    start_time = datetime.now()
    total_processed = 0
    total_success = 0
    total_fail = 0

    with status_container:
        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
        metric_remaining = col_s1.empty()
        metric_completed = col_s2.empty()
        metric_success = col_s3.empty()
        metric_failed = col_s4.empty()
        metric_eta = col_s5.empty()

    current_file_display = st.empty()
    log_display = results_container.empty()
    log_messages = []

    # Continuous processing loop
    while not st.session_state.stop_requested:
        # Get current pending files (refreshes each loop)
        pending_files = get_pending_files(input_folder, output_folder)

        if not pending_files:
            # No files to process, wait and check again
            current_file_display.text("Waiting for new files...")
            time.sleep(2)

            # Update stats
            remaining = len(get_pending_files(input_folder, output_folder))
            completed = get_processed_count(output_folder)
            metric_remaining.metric("Remaining", remaining)
            metric_completed.metric("Completed", completed)
            continue

        batch_size = len(pending_files)
        state.start_session(input_folder, output_folder, batch_size)
        batch_processed = 0

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_file = {
                executor.submit(
                    process_single_pdf,
                    file_path,
                    output_folder,
                    language,
                    deskew,
                    True,  # clean (not used)
                    delete_input
                ): file_path
                for file_path in pending_files
            }

            for future in as_completed(future_to_file):
                if st.session_state.stop_requested:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                file_path = future_to_file[future]
                file_name = os.path.basename(file_path)

                try:
                    result = future.result()
                    batch_processed += 1
                    total_processed += 1

                    if result.success:
                        total_success += 1
                        state.mark_processed(result.file_name, True)
                        log_msg = f"✅ {result.file_name} ({format_time(result.processing_time)})"
                    else:
                        total_fail += 1
                        state.mark_processed(result.file_name, False)
                        log_msg = f"❌ {result.file_name}: {result.error}"

                    log_messages.append(log_msg)

                except Exception as e:
                    batch_processed += 1
                    total_processed += 1
                    total_fail += 1
                    log_messages.append(f"❌ {file_name}: {str(e)}")
                    state.mark_processed(file_name, False)

                # Update UI with real-time counts
                elapsed = (datetime.now() - start_time).total_seconds()
                progress = batch_processed / batch_size

                progress_bar.progress(progress)
                current_file_display.text(f"Processing: {file_name}")

                # Real-time folder counts
                remaining = len(get_pending_files(input_folder, output_folder))
                completed = get_processed_count(output_folder)

                metric_remaining.metric("Remaining", remaining)
                metric_completed.metric("Completed", completed)
                metric_success.metric("Success", total_success)
                metric_failed.metric("Failed", total_fail)
                metric_eta.metric("ETA", estimate_remaining_time(
                    batch_processed, batch_size, elapsed
                ))

                log_display.text("\n".join(log_messages[-15:]))

        # Batch complete, check for new files
        progress_bar.progress(1.0)
        current_file_display.text("Batch complete. Checking for new files...")
        time.sleep(1)

    # Processing stopped
    st.session_state.processing = False
    total_time = (datetime.now() - start_time).total_seconds()
    current_file_display.empty()

    st.success(f"Processing stopped. {total_success} succeeded, {total_fail} failed in {format_time(total_time)}")


def main():
    st.title("PDF24 Batch OCR Processor")
    st.caption("Crash-resistant parallel OCR processing for Windows")

    # Create default folders if they don't exist
    ensure_folder_exists(config.DEFAULT_INPUT_FOLDER)
    ensure_folder_exists(config.DEFAULT_OUTPUT_FOLDER)

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

        delete_input = st.checkbox(
            "Delete input after success",
            value=saved_settings["delete_input"],
            help="Remove original file after successful OCR"
        )

        # Save all settings when changed
        save_settings({
            "auto_start": auto_start,
            "workers": num_workers,
            "language": language,
            "deskew": deskew,
            "delete_input": delete_input
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

    pending_files = get_pending_files(input_folder, output_folder)

    # Status display
    col_status1, col_status2, col_status3 = st.columns(3)
    with col_status1:
        st.metric("Pending", len(pending_files))
    with col_status2:
        st.metric("Completed", get_processed_count(output_folder))
    with col_status3:
        st.metric("Workers", num_workers)

    st.divider()

    # Start/Stop buttons
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

    # Auto-start logic (runs once on boot)
    should_auto_start = (
        auto_start and
        not st.session_state.auto_started and
        not st.session_state.processing and
        len(pending_files) > 0
    )

    if start_button or should_auto_start:
        if should_auto_start:
            st.session_state.auto_started = True
            st.info("Auto-starting processing...")

        st.session_state.processing = True
        st.session_state.stop_requested = False

        run_processing(
            input_folder, output_folder, num_workers,
            language, deskew, delete_input
        )


if __name__ == "__main__":
    main()
