import os
import shutil
import sys
import time
from datetime import datetime

from ccgp.config import ATTACHMENTS_DIR, CLEAN_THRESHOLD
from ccgp.main import main


def should_delete_folder(folder_name: str, days_threshold: int = 3) -> bool:
    """Return True if folder suffix matches _YYYYMMDD and is older than threshold."""
    try:
        if "_" in folder_name:
            date_str = folder_name.split("_")[-1]
            if len(date_str) == 8 and date_str.isdigit():
                folder_date = datetime.strptime(date_str, "%Y%m%d")
                days_diff = (datetime.now() - folder_date).days
                return days_diff >= days_threshold
    except Exception as e:
        print(f"failed to parse folder date for {folder_name}: {e}")
    return False


def cleanup_old_folders(attachments_path: str, days_threshold: int = 3) -> None:
    """Delete old attachment folders after run."""
    if not os.path.exists(attachments_path):
        print(f"path not exists: {attachments_path}")
        return

    cleaned_folders = []
    kept_folders = []

    for item in os.listdir(attachments_path):
        item_path = os.path.join(attachments_path, item)
        if not os.path.isdir(item_path):
            continue

        if should_delete_folder(item, days_threshold):
            try:
                shutil.rmtree(item_path)
                cleaned_folders.append(item)
                print(f"deleted expired folder: {item}")
            except Exception as e:
                print(f"failed to delete folder {item}: {e}")
        else:
            kept_folders.append(item)

    print(f"cleaned folders: {len(cleaned_folders)}")
    print(f"kept folders: {len(kept_folders)}")


def run_multiple_main_calls() -> None:
    """
    Sync behavior with main.py:
    - Default (search mode): call main() once. Do NOT iterate old start_urls.
    - Legacy list mode (--no-search): keep old behavior and iterate two start_urls.
    """
    original_argv = sys.argv.copy()

    use_legacy_list_mode = "--no-search" in original_argv

    if not use_legacy_list_mode:
        print("running search-prefilter mode once (no start_urls loop)")
        try:
            main()
            print("search-prefilter run completed")
        except Exception as e:
            print(f"search-prefilter run failed: {e}")
    else:
        start_urls = [
            "https://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm",
            "https://www.ccgp.gov.cn/cggg/zygg/gkzb/index.htm",
        ]

        preserved_args = []
        i = 1
        while i < len(original_argv):
            if original_argv[i] == "--start":
                i += 2
                continue
            preserved_args.append(original_argv[i])
            i += 1

        for idx, url in enumerate(start_urls, 1):
            print(f"running legacy list mode {idx}/{len(start_urls)}: {url}")
            sys.argv = [original_argv[0], "--start", url] + preserved_args
            try:
                main()
                print(f"legacy run {idx} completed")
            except Exception as e:
                print(f"legacy run {idx} failed: {e}")

            if idx < len(start_urls):
                time.sleep(5)

    sys.argv = original_argv
    print("all runs finished, cleaning old attachment folders...")
    cleanup_old_folders(ATTACHMENTS_DIR, CLEAN_THRESHOLD)
    print("cleanup completed")


if __name__ == "__main__":
    run_multiple_main_calls()
