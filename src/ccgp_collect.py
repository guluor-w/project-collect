import os
import shutil
import sys
import time
from datetime import datetime

from ccgp.config import ATTACHMENTS_DIR, CLEAN_THRESHOLD
from ccgp.main import main, SearchNetworkError


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
        print(f"解析文件夹日期失败 {folder_name}: {e}")
    return False


def cleanup_old_folders(attachments_path: str, days_threshold: int = 3) -> None:
    """Delete old attachment folders after run."""
    if not os.path.exists(attachments_path):
        print(f"路径不存在: {attachments_path}")
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
                print(f"删除过期文件夹: {item}")
            except Exception as e:
                print(f"删除文件夹失败 {item}: {e}")
        else:
            kept_folders.append(item)

    print(f"已清理文件夹数: {len(cleaned_folders)}")
    print(f"保留文件夹数: {len(kept_folders)}")


def run_multiple_main_calls() -> None:
    """
    执行采集任务，支持两种模式：

    - 默认（search 模式）：调用一次 main()，使用 search.ccgp.gov.cn 预筛选。
      若 search.ccgp.gov.cn 不可达（SearchNetworkError），自动回退至列表页模式。
    - 列表页模式（--no-search 或自动回退）：对地方/中央两个入口各调用一次 main()。
    """
    original_argv = sys.argv.copy()

    use_legacy_list_mode = "--no-search" in original_argv

    if not use_legacy_list_mode:
        print("运行单次搜索预筛选模式（不轮询 start_urls）")
        try:
            main()
            print("搜索预筛选运行完成")
        except SearchNetworkError as e:
            print(f"search.ccgp.gov.cn 不可达，自动切换至列表页模式: {e}")
            use_legacy_list_mode = True
        except Exception as e:
            print(f"搜索预筛选运行失败: {e}")

    if use_legacy_list_mode:
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
            if original_argv[i] == "--no-search":
                i += 1
                continue  # 跳过原有标志，在下方统一补充，避免重复
            preserved_args.append(original_argv[i])
            i += 1
        # 无论是手动指定还是自动回退，均确保 --no-search 排在最前以触发列表页模式
        preserved_args = ["--no-search"] + preserved_args

        for idx, url in enumerate(start_urls, 1):
            print(f"运行传统列表模式 {idx}/{len(start_urls)}: {url}")
            sys.argv = [original_argv[0], "--start", url] + preserved_args
            try:
                main()
                print(f"传统模式运行 {idx} 完成")
            except Exception as e:
                print(f"传统模式运行 {idx} 失败: {e}")

            if idx < len(start_urls):
                time.sleep(5)

    sys.argv = original_argv
    print("所有运行结束，正在清理旧附件文件夹...")
    cleanup_old_folders(ATTACHMENTS_DIR, CLEAN_THRESHOLD)
    print("清理完成")


if __name__ == "__main__":
    run_multiple_main_calls()
