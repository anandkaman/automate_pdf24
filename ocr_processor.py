"""
Core OCR processing logic using PDF24 OCR CLI (pdf24-Ocr.exe)
Uses independent worker architecture where each worker manages its own file lifecycle.
"""
import subprocess
import os
import shutil
import logging
import time
import queue
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import config
from utils import check_disk_space, find_error_folder_fallback

# Global lock for atomic file claiming - ensures only one worker can claim a file at a time
_claim_lock = threading.Lock()

# Track files currently being processed (prevents multiple workers claiming same file)
_claimed_files = set()

# Track crash recovery retry counts: {file_name: retry_count}
_crash_recovery_retries = {}

# Setup logging - caller handles handlers
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class ProcessingResult:
    """Result of a single file processing"""
    file_name: str
    success: bool
    message: str
    processing_time: float = 0.0
    error: Optional[str] = None


def validate_ocr_tool() -> bool:
    """Check if PDF24 OCR tool exists at configured path"""
    return os.path.exists(config.OCR_TOOL_PATH)


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its children (Windows)"""
    try:
        # Use taskkill to kill process tree on Windows
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        logger.debug(f"Killed process tree for PID {pid}")
    except Exception as e:
        logger.warning(f"Could not kill process tree {pid}: {e}")


def kill_pdf24_processes() -> None:
    """Kill any hanging PDF24 OCR processes"""
    try:
        # Kill pdf24-Ocr.exe processes
        subprocess.run(
            ["taskkill", "/F", "/IM", "pdf24-Ocr.exe"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        logger.debug("Killed hanging PDF24 processes")
    except Exception as e:
        logger.warning(f"Could not kill PDF24 processes: {e}")


def build_ocr_command(input_path: str, output_path: str,
                      language: str = None, deskew: bool = True,
                      dpi: int = None) -> list:
    """
    Build the PDF24 OCR CLI command

    Args:
        input_path: Path to input PDF file
        output_path: Path for output PDF file
        language: OCR language(s), e.g., "eng+kan"
        deskew: Enable deskew correction
        dpi: DPI for processing

    Returns:
        List of command arguments
    """
    lang = language or config.OCR_LANGUAGES
    dpi_val = dpi or config.OCR_DPI

    # pdf24-Ocr.exe syntax:
    # pdf24-Ocr.exe -outputFile "output.pdf" -language eng+kan -dpi 300 -deskew "input.pdf"
    cmd = [
        config.OCR_TOOL_PATH,
        "-outputFile", output_path,
        "-language", lang,
        "-dpi", str(dpi_val),
    ]

    if deskew:
        cmd.append("-deskew")

    if config.OCR_REMOVE_BACKGROUND:
        cmd.append("-removeBackground")

    # Input file goes last
    cmd.append(input_path)

    return cmd


def cleanup_partial_output(output_path: str) -> None:
    """Remove partial/corrupted output file if it exists"""
    try:
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size == 0:  # Empty file - definitely partial
                os.remove(output_path)
                logger.debug(f"Removed empty output file: {output_path}")
    except Exception as e:
        logger.warning(f"Could not clean up partial output: {e}")


def move_to_error_folder(file_path: str, error_folder: str) -> bool:
    """Move a failed file to the error folder"""
    try:
        if not os.path.exists(error_folder):
            os.makedirs(error_folder)

        file_name = os.path.basename(file_path)
        error_path = os.path.join(error_folder, file_name)

        # If file already exists in error folder, add timestamp
        if os.path.exists(error_path):
            name, ext = os.path.splitext(file_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            error_path = os.path.join(error_folder, f"{name}_{timestamp}{ext}")

        shutil.move(file_path, error_path)
        logger.info(f"Moved failed file to error folder: {file_name}")
        return True
    except Exception as e:
        logger.error(f"Could not move file to error folder: {e}")
        return False


def claim_file_for_processing(input_folder: str, output_folder: str, processing_folder: str,
                               duplicate_folder: str = None, error_folder: str = None,
                               min_file_age: float = None) -> Optional[str]:
    """
    Atomically claim ONE file for processing.

    This is the core of the independent worker architecture:
    - Acquires a global lock to prevent race conditions
    - Finds one unclaimed file (not in _claimed_files set)
    - Moves it to Processing folder (if from Input) or marks it claimed (if crash recovery)
    - Adds to _claimed_files set
    - Releases the lock

    IMPORTANT: Never sleeps or blocks while holding the lock.
    If a file is locked (antivirus, copy in progress), it's skipped immediately.
    The file will be picked up in the next polling cycle.

    Args:
        min_file_age: Minimum file age in seconds before claiming (default 3.0).
                      Ensures file copy/antivirus scan is complete.

    Returns:
        Path to claimed file in Processing folder, or None if no files available
    """
    if min_file_age is None:
        min_file_age = getattr(config, 'MIN_FILE_AGE', 1.0)

    with _claim_lock:
        # Ensure processing folder exists
        if not os.path.exists(processing_folder):
            os.makedirs(processing_folder)

        # First check Processing folder for crash recovery files
        if os.path.exists(processing_folder):
            for f in os.listdir(processing_folder):
                if f.lower().endswith('.pdf'):
                    processing_path = os.path.join(processing_folder, f)
                    output_path = os.path.join(output_folder, f)

                    # Skip if already claimed by another worker
                    if processing_path in _claimed_files:
                        continue

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        # Already processed - clean up
                        try:
                            os.remove(processing_path)
                            _crash_recovery_retries.pop(f, None)
                            logger.info(f"Cleanup: removed already-processed file: {f}")
                        except Exception as e:
                            logger.warning(f"Could not cleanup {f}: {e}")
                    else:
                        # Crash recovery - check retry limit
                        max_retries = getattr(config, 'MAX_CRASH_RECOVERY_RETRIES', 3)
                        retry_count = _crash_recovery_retries.get(f, 0)

                        if retry_count >= max_retries:
                            # Exceeded retry limit - move to error folder directly
                            logger.error(f"Crash recovery: {f} failed {retry_count} times, moving to Error")
                            if error_folder:
                                try:
                                    error_path = find_error_folder_fallback(error_folder)
                                    move_to_error_folder(processing_path, error_path)
                                except Exception as e:
                                    logger.error(f"Could not move {f} to error: {e}")
                            _crash_recovery_retries.pop(f, None)
                            continue

                        # Claim for retry
                        _crash_recovery_retries[f] = retry_count + 1
                        _claimed_files.add(processing_path)
                        logger.info(f"Crash recovery: claiming {f} (attempt {retry_count + 1}/{max_retries})")
                        return processing_path

        # Get list of files in Input folder
        if not os.path.exists(input_folder):
            return None

        try:
            input_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]
        except Exception as e:
            logger.error(f"Error listing input folder: {e}")
            return None

        if not input_files:
            return None

        current_time = time.time()

        # Try to claim the first available file
        for file_name in sorted(input_files):
            input_path = os.path.join(input_folder, file_name)
            output_path = os.path.join(output_folder, file_name)
            processing_path = os.path.join(processing_folder, file_name)

            # Skip if already claimed
            if processing_path in _claimed_files:
                continue

            # Skip if already being processed (file exists in Processing)
            if os.path.exists(processing_path):
                continue

            # Skip if already processed (output exists)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                # Move to duplicate folder if specified
                if duplicate_folder:
                    try:
                        move_to_duplicate_folder(input_path, duplicate_folder)
                    except Exception as e:
                        logger.warning(f"Could not move duplicate {file_name}: {e}")
                continue

            # Skip if file is too new (copy/antivirus scan may be in progress)
            try:
                file_mtime = os.path.getmtime(input_path)
                file_age = current_time - file_mtime
                if file_age < min_file_age:
                    logger.debug(f"Skipping {file_name}: too new ({file_age:.1f}s < {min_file_age}s)")
                    continue
            except OSError:
                continue  # File disappeared

            # Try to claim this file by moving to Processing (NO RETRY - skip if locked)
            try:
                if not os.path.exists(input_path):
                    continue  # File was taken by another process

                shutil.move(input_path, processing_path)
                _claimed_files.add(processing_path)
                logger.debug(f"Claimed: {file_name}")
                return processing_path

            except PermissionError:
                # File is locked (antivirus, copy, etc.) - skip and try next
                # Will be picked up in next polling cycle
                logger.debug(f"Skipping {file_name}: file locked (will retry next cycle)")
                continue
            except FileNotFoundError:
                continue  # File was claimed by another worker
            except Exception as e:
                logger.warning(f"Error claiming {file_name}: {e}")
                continue

        return None  # No files available to claim


def release_claimed_file(processing_path: str) -> None:
    """Remove a file from the claimed set after processing is complete."""
    with _claim_lock:
        _claimed_files.discard(processing_path)


def move_to_processing_folder(file_path: str, processing_folder: str, max_retries: int = 5) -> Optional[str]:
    """
    Move a file to the processing folder before OCR.
    Returns the new path in processing folder, or None if move failed.
    Includes retry logic for files that are temporarily locked (e.g., by Windows copy, antivirus).

    NOTE: For the independent worker architecture, use claim_file_for_processing() instead.
    This function is kept for backward compatibility.
    """
    if not os.path.exists(processing_folder):
        os.makedirs(processing_folder)

    file_name = os.path.basename(file_path)
    processing_path = os.path.join(processing_folder, file_name)

    # If file already exists in processing folder (crash recovery), use it
    if os.path.exists(processing_path):
        logger.info(f"File already in processing folder (crash recovery): {file_name}")
        return processing_path

    # Retry loop for temporarily locked files
    for attempt in range(max_retries):
        try:
            # If source doesn't exist anymore, check processing folder
            if not os.path.exists(file_path):
                if os.path.exists(processing_path):
                    return processing_path
                return None

            shutil.move(file_path, processing_path)
            logger.debug(f"Moved to processing: {file_name}")
            return processing_path

        except PermissionError as e:
            if attempt < max_retries - 1:
                # Wait longer each retry: 0.5s, 1s, 2s, 4s, 8s
                wait_time = 0.5 * (2 ** attempt)
                logger.debug(f"File locked, retry {attempt + 1}/{max_retries} in {wait_time}s: {file_name}")
                time.sleep(wait_time)
            else:
                logger.warning(f"File still locked after {max_retries} retries, skipping: {file_name}")
                return None
        except Exception as e:
            logger.error(f"Could not move file to processing folder: {e}")
            return None

    return None


def prepare_batch_for_processing(input_folder: str, output_folder: str, processing_folder: str,
                                  duplicate_folder: str = None, error_folder: str = None) -> list:
    """
    Move all pending files from Input to Processing folder SEQUENTIALLY.
    This prevents race conditions when parallel workers try to grab files.
    Also cleans up already-processed files from Processing folder.

    Returns:
        List of file paths in the Processing folder ready for OCR
    """
    ready_files = []

    # First, check Processing folder (crash recovery + cleanup)
    if os.path.exists(processing_folder):
        for f in os.listdir(processing_folder):
            if f.lower().endswith('.pdf'):
                processing_path = os.path.join(processing_folder, f)
                output_path = os.path.join(output_folder, f)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    # Already processed - clean up from Processing folder
                    try:
                        os.remove(processing_path)
                        logger.info(f"Cleanup: removed already-processed file from Processing: {f}")
                    except Exception as e:
                        logger.warning(f"Could not cleanup {f} from Processing: {e}")
                else:
                    # Not yet processed - add to ready list (crash recovery)
                    ready_files.append(processing_path)
                    logger.info(f"Crash recovery: {f} found in Processing folder")

    # Get pending files from Input folder
    pending = get_pending_files(input_folder, output_folder, duplicate_folder, error_folder)

    # Move files from Input to Processing sequentially
    for file_path in pending:
        file_name = os.path.basename(file_path)
        processing_path = os.path.join(processing_folder, file_name)

        # Skip if already in ready list (from crash recovery)
        if processing_path in ready_files:
            continue

        moved_path = move_to_processing_folder(file_path, processing_folder)
        if moved_path:
            ready_files.append(moved_path)

    return ready_files


def process_single_pdf(file_path: str, output_folder: str,
                       language: str = None, deskew: bool = True,
                       clean: bool = True, delete_on_success: bool = True,
                       max_retries: int = 2, error_folder: str = None,
                       processing_folder: str = None) -> ProcessingResult:
    """
    Process a single PDF file through OCR with retry logic.
    Uses Processing folder to avoid file lock conflicts with PDF24.

    Args:
        file_path: Path to the input PDF
        output_folder: Folder to save OCR'd PDF
        language: OCR language(s)
        deskew: Enable deskew
        clean: Not used (kept for API compatibility)
        delete_on_success: Delete input file after successful processing
        max_retries: Maximum retry attempts on failure (default: 2)
        error_folder: Folder to move failed files (optional)
        processing_folder: Temp folder for files being processed (optional)

    Returns:
        ProcessingResult with status and details
    """
    file_name = os.path.basename(file_path)
    output_path = os.path.join(output_folder, file_name)
    start_time = datetime.now()
    last_error = None
    working_path = file_path  # Will be updated if using processing folder

    logger.info(f"Starting OCR for: {file_name}")

    # Check if output already exists (skip if already processed)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        logger.info(f"Output already exists, skipping: {file_name}")
        # Clean up input if it exists and delete_on_success is True
        if delete_on_success and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return ProcessingResult(
            file_name=file_name,
            success=True,
            message="Already processed (output exists)"
        )

    # Check if input file still exists (race condition prevention)
    if not os.path.exists(file_path):
        logger.warning(f"Input file no longer exists: {file_name}")
        return ProcessingResult(
            file_name=file_name,
            success=False,
            message="File not found",
            error="Input file was removed or moved"
        )

    # Move to processing folder if specified (eliminates WinError 32)
    if processing_folder:
        working_path = move_to_processing_folder(file_path, processing_folder)
        if not working_path:
            return ProcessingResult(
                file_name=file_name,
                success=False,
                message="Could not move to processing folder",
                error="File move failed"
            )

    # Build command using working_path (either original or in processing folder)
    cmd = build_ocr_command(working_path, output_path, language, deskew)

    logger.debug(f"Command: {' '.join(cmd)}")

    # Retry loop
    for attempt in range(max_retries):

        try:
            # Clean up any partial output from previous attempt
            cleanup_partial_output(output_path)

            # Run PDF24 OCR CLI using Popen for better process control
            # Use HIGH_PRIORITY_CLASS for maximum performance
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.HIGH_PRIORITY_CLASS

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creation_flags
            )

            try:
                stdout, stderr = process.communicate(timeout=600)  # 10 minute timeout
            except subprocess.TimeoutExpired:
                # Kill ONLY this specific process tree on timeout
                logger.warning(f"TIMEOUT: {file_name} (attempt {attempt + 1}/{max_retries}) - killing specific process...")
                kill_process_tree(process.pid)
                process.kill()
                try:
                    process.communicate(timeout=5)
                except:
                    pass
                cleanup_partial_output(output_path)
                last_error = "Processing exceeded 10 minute limit"

                if attempt < max_retries - 1:
                    logger.info(f"Retrying {file_name}...")
                    time.sleep(2)
                    continue
                else:
                    processing_time = (datetime.now() - start_time).total_seconds()
                    if error_folder:
                        move_to_error_folder(working_path, error_folder)
                    return ProcessingResult(
                        file_name=file_name,
                        success=False,
                        message=f"Timeout after {max_retries} attempts",
                        error=last_error,
                        processing_time=processing_time
                    )

            processing_time = (datetime.now() - start_time).total_seconds()

            # Check if output was created
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                # Success - delete from processing folder (no lock conflict)
                if delete_on_success:
                    try:
                        # Small delay to ensure PDF24 releases handle
                        time.sleep(0.3)
                        os.remove(working_path)
                        logger.debug(f"Deleted processed file: {file_name}")
                    except Exception as e:
                        logger.warning(f"Could not delete {file_name}: {e}")

                return ProcessingResult(
                    file_name=file_name,
                    success=True,
                    message=f"Processed successfully",
                    processing_time=processing_time
                )
            else:
                # Output not created - remove ONLY the partial output for this file
                cleanup_partial_output(output_path)
                
                # Capture specific error details for diagnostic
                error_details = []
                if stdout: error_details.append(f"STDOUT: {stdout.strip()[-200:]}")
                if stderr: error_details.append(f"STDERR: {stderr.strip()[-500:]}")
                
                last_error = " | ".join(error_details) or "Output file not created"
                logger.warning(f"FAILED: {file_name} (attempt {attempt + 1}/{max_retries}) - {last_error}")

                if attempt < max_retries - 1:
                    logger.info(f"Retrying {file_name}...")
                    time.sleep(2)  # Brief pause before retry
                    continue
                else:
                    logger.error(f"FAILED: {file_name} - all {max_retries} attempts failed")
                    # Move to error folder
                    if error_folder:
                        move_to_error_folder(working_path, error_folder)
                    return ProcessingResult(
                        file_name=file_name,
                        success=False,
                        message=f"OCR failed after {max_retries} attempts",
                        error=last_error,
                        processing_time=processing_time
                    )

        except Exception as e:
            # Kill any hanging PDF24 processes on crash
            kill_pdf24_processes()
            cleanup_partial_output(output_path)
            last_error = str(e)

            if attempt < max_retries - 1:
                logger.warning(f"ERROR: {file_name} (attempt {attempt + 1}/{max_retries}) - {last_error}")
                logger.info(f"Retrying {file_name}...")
                time.sleep(2)
                continue
            else:
                processing_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"ERROR: {file_name} - all {max_retries} attempts failed - {last_error}")
                # Move to error folder
                if error_folder:
                    move_to_error_folder(working_path, error_folder)
                return ProcessingResult(
                    file_name=file_name,
                    success=False,
                    message=f"Processing error after {max_retries} attempts",
                    error=last_error,
                    processing_time=processing_time
                )

    # Should never reach here, but just in case
    processing_time = (datetime.now() - start_time).total_seconds()
    return ProcessingResult(
        file_name=file_name,
        success=False,
        message="Unknown error",
        error=last_error or "Unexpected exit from retry loop",
        processing_time=processing_time
    )


def move_to_duplicate_folder(file_path: str, duplicate_folder: str) -> bool:
    """Move a duplicate file to the duplicate folder"""
    try:
        if not os.path.exists(duplicate_folder):
            os.makedirs(duplicate_folder)

        file_name = os.path.basename(file_path)
        dup_path = os.path.join(duplicate_folder, file_name)

        # If file already exists in duplicate folder, add timestamp
        if os.path.exists(dup_path):
            name, ext = os.path.splitext(file_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dup_path = os.path.join(duplicate_folder, f"{name}_{timestamp}{ext}")

        shutil.move(file_path, dup_path)
        logger.info(f"Moved duplicate file: {file_name}")
        return True
    except Exception as e:
        logger.error(f"Could not move duplicate file: {e}")
        return False


def get_pending_files(input_folder: str, output_folder: str, duplicate_folder: str = None, error_folder: str = None) -> list:
    """
    Get list of PDF files that haven't been processed yet.
    Moves duplicates (already in output) to duplicate folder if provided.
    Moves non-PDF files to error folder if provided.

    Args:
        input_folder: Folder with input PDFs
        output_folder: Folder with processed PDFs
        duplicate_folder: Folder to move duplicates (optional)
        error_folder: Folder to move non-PDF files (optional)

    Returns:
        List of file paths that need processing
    """
    try:
        if not os.path.exists(input_folder):
            return []

        # Get all files in input folder
        all_files = os.listdir(input_folder)

        # Move non-PDF files to error folder
        if error_folder:
            for file_name in all_files:
                if not file_name.lower().endswith('.pdf'):
                    input_path = os.path.join(input_folder, file_name)
                    if os.path.isfile(input_path):  # Skip directories
                        logger.warning(f"Non-PDF file detected: {file_name} - moving to Error folder")
                        move_to_error_folder(input_path, error_folder)

        # Get all PDFs in input folder
        input_files = [
            f for f in os.listdir(input_folder)
            if f.lower().endswith('.pdf')
        ]

        # Filter out already processed and move duplicates
        pending = []
        for file_name in input_files:
            input_path = os.path.join(input_folder, file_name)
            output_path = os.path.join(output_folder, file_name)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                # Already processed - move to duplicate folder
                if duplicate_folder:
                    move_to_duplicate_folder(input_path, duplicate_folder)
                # else: just skip (stays in Input)
            else:
                pending.append(input_path)

        return sorted(pending)
    except PermissionError as e:
        logger.error(f"Permission denied accessing folder: {e}")
        return []
    except OSError as e:
        logger.error(f"Error accessing folder: {e}")
        return []


def get_processed_count(output_folder: str) -> int:
    """Get count of already processed files in output folder"""
    if not os.path.exists(output_folder):
        return 0
    return len([f for f in os.listdir(output_folder) if f.lower().endswith('.pdf')])


def independent_worker_task(input_folder: str, output_folder: str, processing_folder: str,
                            error_folder: str, duplicate_folder: str,
                            language: str, deskew: bool,
                            max_retries: int = 2,
                            cleanup_queue: Optional[queue.Queue] = None) -> Optional[ProcessingResult]:
    """
    Independent worker task - claims and processes ONE file.

    This is the core of the new architecture where each worker:
    1. Atomically claims ONE file (moves from Input to Processing)
    2. Processes it with OCR
    3. On success: enqueues cleanup to cleanup_queue (non-blocking) then returns immediately
    4. On failure: moves to error folder synchronously (fast, no sleep needed)
    5. Releases the claim

    Returns:
        ProcessingResult if a file was processed, None if no files to process
    """
    # Step 1: Claim a file atomically
    processing_path = claim_file_for_processing(
        input_folder, output_folder, processing_folder,
        duplicate_folder, error_folder
    )

    if not processing_path:
        return None  # No files to process

    file_name = os.path.basename(processing_path)
    output_path = os.path.join(output_folder, file_name)
    start_time = datetime.now()
    last_error = None

    try:
        logger.info(f"Processing: {file_name}")

        # Step 2: Process the file
        cmd = build_ocr_command(processing_path, output_path, language, deskew)

        for attempt in range(max_retries):
            try:
                # Clean up any partial output from previous attempt
                cleanup_partial_output(output_path)

                # Run PDF24 OCR CLI
                creation_flags = 0
                if os.name == 'nt':
                    creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.HIGH_PRIORITY_CLASS

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creation_flags
                )

                try:
                    stdout, stderr = process.communicate(timeout=600)  # 10 minute timeout
                except subprocess.TimeoutExpired:
                    logger.warning(f"TIMEOUT: {file_name} (attempt {attempt + 1}/{max_retries})")
                    kill_process_tree(process.pid)
                    process.kill()
                    try:
                        process.communicate(timeout=5)
                    except:
                        pass
                    cleanup_partial_output(output_path)
                    last_error = "Processing exceeded 10 minute limit"

                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    else:
                        break

                processing_time = (datetime.now() - start_time).total_seconds()

                # Step 3: Check result and cleanup
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    # SUCCESS - clear retry counter, enqueue async cleanup, return immediately
                    _crash_recovery_retries.pop(file_name, None)

                    if cleanup_queue is not None:
                        # Hand off to cleanup thread - worker is free NOW
                        cleanup_queue.put(processing_path)
                    else:
                        # Fallback: sync cleanup (called without a queue)
                        for del_attempt in range(3):
                            try:
                                time.sleep(0.5)
                                os.remove(processing_path)
                                break
                            except PermissionError:
                                if del_attempt < 2:
                                    time.sleep(1)
                                else:
                                    logger.warning(f"Could not delete {file_name} from Processing (will retry later)")
                            except FileNotFoundError:
                                break
                            except Exception as e:
                                logger.warning(f"Cleanup error for {file_name}: {e}")
                                break

                    return ProcessingResult(
                        file_name=file_name,
                        success=True,
                        message="Processed successfully",
                        processing_time=processing_time
                    )
                else:
                    # FAILED - output not created
                    cleanup_partial_output(output_path)
                    error_details = []
                    if stdout:
                        error_details.append(stdout.strip()[-200:])
                    if stderr:
                        error_details.append(stderr.strip()[-500:])
                    last_error = " | ".join(error_details) or "Output file not created"

                    if attempt < max_retries - 1:
                        logger.warning(f"FAILED: {file_name} (attempt {attempt + 1}/{max_retries}) - {last_error}")
                        time.sleep(2)
                        continue
                    else:
                        break

            except Exception as e:
                kill_pdf24_processes()
                cleanup_partial_output(output_path)
                last_error = str(e)

                if attempt < max_retries - 1:
                    logger.warning(f"ERROR: {file_name} (attempt {attempt + 1}/{max_retries}) - {last_error}")
                    time.sleep(2)
                    continue
                else:
                    break

        # All retries failed - move to Error folder
        processing_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"FAILED: {file_name} - {last_error}")

        if error_folder:
            move_to_error_folder(processing_path, error_folder)

        return ProcessingResult(
            file_name=file_name,
            success=False,
            message=f"OCR failed after {max_retries} attempts",
            error=last_error,
            processing_time=processing_time
        )

    finally:
        # ALWAYS release claim, even if unexpected exception occurs
        release_claimed_file(processing_path)


def cleanup_processed_inputs(input_folder: str, output_folder: str) -> int:
    """
    Delete input files that have already been processed (output exists).
    Call this AFTER batch processing completes to avoid race conditions.

    Returns:
        Number of files cleaned up
    """
    cleaned = 0
    try:
        if not os.path.exists(input_folder):
            return 0

        input_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]

        for file_name in input_files:
            input_path = os.path.join(input_folder, file_name)
            output_path = os.path.join(output_folder, file_name)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                try:
                    os.remove(input_path)
                    logger.info(f"Storage Cleanup: Deleted processed input {file_name}")
                    cleaned += 1
                except Exception as e:
                    logger.warning(f"Could not delete {file_name}: {e}")

        return cleaned
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        return cleaned


def process_batch(
    input_folder: str,
    output_folder: str,
    processing_folder: str,
    error_folder: str,
    duplicate_folder: str,
    language: str,
    deskew: bool,
    num_workers: int,
    max_retries: int = 2,
    on_result: Callable[[ProcessingResult], None] = None,
    should_stop: Callable[[], bool] = None
) -> Tuple[int, int]:
    """
    Shared batch processing function used by both GUI and background worker.

    Architecture:
    - OCR workers claim + process + return immediately (no cleanup sleep)
    - A single cleanup thread handles post-OCR deletes from Processing folder
    - Termination: all N workers independently return None (no files left)
    - New files arriving mid-batch are automatically picked up (no max_tasks cap)

    Args:
        input_folder: Folder with input PDFs
        output_folder: Folder for processed PDFs
        processing_folder: Temp folder during OCR
        error_folder: Folder for failed files
        duplicate_folder: Folder for duplicates
        language: OCR language(s)
        deskew: Enable deskew
        num_workers: Number of parallel workers
        max_retries: Max OCR retries per file
        on_result: Callback called with each ProcessingResult (for UI updates)
        should_stop: Callback that returns True if processing should stop

    Returns:
        Tuple of (success_count, fail_count)
    """
    # Check disk space before starting
    if not check_disk_space(output_folder):
        logger.error("STOPPING: Insufficient disk space on output drive")
        return 0, 0

    # Resolve error folder (fallback to another drive if primary is full)
    error_folder = find_error_folder_fallback(error_folder)

    # Count pending files (including crash recovery in Processing folder)
    pending = get_pending_files(input_folder, output_folder, duplicate_folder, error_folder)
    processing_files = []
    if os.path.exists(processing_folder):
        processing_files = [f for f in os.listdir(processing_folder) if f.lower().endswith('.pdf')]

    if not pending and not processing_files:
        return 0, 0

    success_count = 0
    fail_count = 0

    # --- Cleanup thread ---
    # Handles post-OCR deletion of Processing files so OCR workers never sleep.
    # Lifetime is scoped to this process_batch call: started before executor,
    # drained and joined in finally so no ghost threads remain after return.
    _cq = queue.Queue()

    def _cleanup_loop():
        while True:
            path = _cq.get()
            if path is None:          # stop sentinel
                _cq.task_done()
                break
            for attempt in range(3):
                try:
                    time.sleep(0.5)   # Give PDF24 time to release its handle
                    os.remove(path)
                    logger.debug(f"Cleanup: deleted {os.path.basename(path)}")
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(1)
                    else:
                        logger.warning(f"Cleanup: could not delete {os.path.basename(path)} (will be caught by crash recovery)")
                except FileNotFoundError:
                    break             # Already deleted by crash recovery - fine
                except Exception as e:
                    logger.warning(f"Cleanup: unexpected error for {os.path.basename(path)}: {e}")
                    break
            _cq.task_done()

    cleanup_thread = threading.Thread(
        target=_cleanup_loop,
        daemon=True,
        name="ocr-cleanup"
    )
    cleanup_thread.start()

    try:
        def submit_task():
            return executor.submit(
                independent_worker_task,
                input_folder, output_folder, processing_folder,
                error_folder, duplicate_folder,
                language, deskew, max_retries,
                _cq                       # OCR workers enqueue here on success
            )

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            active_futures = set()

            # Fill the pool initially
            for _ in range(num_workers):
                active_futures.add(submit_task())

            # no_file_count counts how many workers in a row found nothing.
            # Resets to 0 the moment any real work is done.
            # When it reaches num_workers, every worker has independently
            # confirmed the queue is empty - batch is done.
            no_file_count = 0

            while active_futures:
                if should_stop and should_stop():
                    break

                # Event-driven: blocks until at least one future completes.
                # Zero polling sleep - replaces the old 100ms busy-wait.
                done, active_futures = wait(active_futures, return_when=FIRST_COMPLETED)

                for future in done:
                    try:
                        result = future.result()
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"Worker task failed: {e}")
                        # Submit replacement so the pool stays full
                        if not (should_stop and should_stop()):
                            active_futures.add(submit_task())
                        continue

                    if result is None:
                        no_file_count += 1
                        # Keep at least one replacement alive while other
                        # workers are still running - catches files that
                        # arrive mid-batch.
                        if no_file_count < num_workers and not (should_stop and should_stop()):
                            active_futures.add(submit_task())
                        # Do NOT reset no_file_count here; it only resets on
                        # real work so consecutive empties accumulate correctly.
                        continue

                    # Real result - reset idle counter, submit replacement
                    no_file_count = 0

                    if result.success:
                        success_count += 1
                        logger.info(f"SUCCESS: {result.file_name}")
                    else:
                        fail_count += 1
                        logger.error(f"FAILED: {result.file_name} - {result.error}")

                    if on_result:
                        on_result(result)

                    if not (should_stop and should_stop()):
                        active_futures.add(submit_task())

                # All workers confirmed empty AND none still running - batch complete.
                # Checking active_futures prevents premature exit when slow files are
                # still in OCR while fast None tasks have already accumulated.
                if no_file_count >= num_workers and not active_futures:
                    break

    finally:
        # Drain the cleanup queue so all Processing files are deleted before
        # this function returns.  Then send the stop sentinel and join the
        # thread.  cleanup_thread is a daemon, so if join() times out (it
        # shouldn't) the OS reclaims it on process exit - no ghost in RAM.
        _cq.join()
        _cq.put(None)
        cleanup_thread.join(timeout=5)

    return success_count, fail_count
