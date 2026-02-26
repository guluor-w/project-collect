import sys
import time
from ccgp.main import main
from ccgp.config import CLEAN_THRESHOLD, ATTACHMENTS_DIR
import os
import shutil
from datetime import datetime

def should_delete_folder(folder_name, days_threshold=3):
    """
    判断文件夹是否超过指定天数，应该被删除
    """    
    try:
        # 格式: 前缀_YYYYMMDD
        if '_' in folder_name:
            date_str = folder_name.split('_')[-1]
            if len(date_str) == 8 and date_str.isdigit():
                folder_date = datetime.strptime(date_str, "%Y%m%d")
                
                today = datetime.now()
                days_diff = (today - folder_date).days
                
                return days_diff >= days_threshold
    except Exception as e:
        print(f"解析文件夹 {folder_name} 日期时出错: {e}")
    
    return False

def cleanup_old_folders(attachments_path, days_threshold=3):
    """
    清理历史附件文件夹
    """
    if not os.path.exists(attachments_path):
        print(f"路径不存在: {attachments_path}")
        return
    
    cleaned_folders = []
    kept_folders = []
    
    for item in os.listdir(attachments_path):
        item_path = os.path.join(attachments_path, item)
        
        if os.path.isdir(item_path):
            if should_delete_folder(item, days_threshold):
                try:
                    shutil.rmtree(item_path)
                    cleaned_folders.append(item)
                    print(f"已删除过期文件夹: {item}")
                except Exception as e:
                    print(f"删除文件夹 {item} 时出错: {e}")
            else:
                kept_folders.append(item)
    
    if cleaned_folders:
        print(f"\n清理了 {len(cleaned_folders)} 个过期文件夹:")
        for folder in cleaned_folders:
            print(f"  - {folder}")
    else:
        print("没有需要清理的过期文件夹")
    
    print(f"保留了 {len(kept_folders)} 个文件夹")

def run_multiple_main_calls():
    
    original_argv = sys.argv.copy()
    start_urls = [
        "https://www.ccgp.gov.cn/cggg/dfgg/gkzb/index.htm",
        "https://www.ccgp.gov.cn/cggg/zygg/gkzb/index.htm", 
    ]
    
    for i, url in enumerate(start_urls, 1):
        print(f"\n执行第 {i} 次调用，URL: {url}")
        print("-" * 50)
        
        # 将真实链接代入命令行
        sys.argv = [sys.argv[0], "--start", url]
        
        try:
            main()
            print(f"第 {i} 次调用完成")
        except Exception as e:
            print(f"第 {i} 次调用失败: {e}")
        
        if i < len(start_urls):
            time.sleep(5)
    
    sys.argv = original_argv
    print("\n所有调用完成，进行过期附录文件的清理...")
    cleanup_old_folders(ATTACHMENTS_DIR, CLEAN_THRESHOLD)
    print("最终清理完成")

if __name__ == "__main__":
    run_multiple_main_calls()