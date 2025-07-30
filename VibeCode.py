#import pandas as pd
#import matplotlib.pyplot as plt

## 讀取 CSV 文件
#df = pd.read_csv('C:\\Users\\OttoWei\\source\\repos\\VibeCode\\temperatures.csv')

## 將 'date' 欄位轉換為日期時間格式
#df['date'] = pd.to_datetime(df['date'])

## 創建圖表
#plt.figure(figsize=(10, 5))
#plt.plot(df['date'], df['temperature'], marker='o')
#plt.title('Daily Temperatures')
#plt.xlabel('Date')
#plt.ylabel('Temperatures')
#plt.grid(True)

## 保存並顯示圖表
#plt.savefig('temperature_plot.png')
#plt.show()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iPhone照片讀取程式 (修正版本)
專為iOS 18.5和iPhone 15 Pro Max優化
修正模組導入和AFC服務問題
"""

import os
import sys
import json
import threading
import signal
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
    from pymobiledevice3.services.house_arrest import HouseArrestService
    from pymobiledevice3.exceptions import *
    from pymobiledevice3 import *
    # 移除有問題的PhotoLibraryService導入
except ImportError as e:
    print(f"導入錯誤: {e}")
    print("請安裝最新版本: pip install pymobiledevice3")
    sys.exit(1)

import logging

# 設定詳細日誌
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('iphone_reader.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class InterruptibleOperation:
    """可中斷操作的基礎類別"""
    def __init__(self):
        self.should_stop = threading.Event()
        self.progress_callback = None
        self.status_message = ""
        
    def stop(self):
        """設置停止標誌"""
        self.should_stop.set()
        logger.info("⏹ 收到停止信號")
    
    def is_stopped(self):
        """檢查是否應該停止"""
        return self.should_stop.is_set()
    
    def reset(self):
        """重置停止狀態"""
        self.should_stop.clear()
    
    def set_progress_callback(self, callback):
        """設置進度回調函數"""
        self.progress_callback = callback
    
    def update_progress(self, current, total, message=""):
        """更新進度"""
        self.status_message = message
        if self.progress_callback:
            self.progress_callback(current, total, message)

class SafeiPhonePhotoReader(InterruptibleOperation):
    def __init__(self):
        super().__init__()
        self.lockdown = None
        self.afc = None
        self.device_info = {}
        self.max_workers = 4  # 降低並發數以提高穩定性
        self.found_photos = []
        self.scan_progress = {"current": 0, "total": 0, "message": ""}
        
        # 設置Ctrl+C處理
        signal.signal(signal.SIGINT, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """處理Ctrl+C信號"""
        print("\n\n⚠️  檢測到中斷信號 (Ctrl+C)")
        print("正在安全停止操作...")
        self.stop()
        
    def connect_device(self):
        """增強的設備連接功能"""
        if self.is_stopped():
            return False
            
        try:
            self.update_progress(0, 100, "正在搜索iPhone設備...")
            logger.info("正在搜索iPhone設備...")
            
            self.lockdown = create_using_usbmux()
            
            if self.is_stopped():
                return False
            
            # 獲取設備詳細信息
            device_values = self.lockdown.all_values
            self.device_info = {
                'name': device_values.get('DeviceName', 'Unknown'),
                'model': device_values.get('ProductType', 'Unknown'),
                'ios_version': device_values.get('ProductVersion', 'Unknown'),
                'build_version': device_values.get('BuildVersion', 'Unknown'),
                'serial': device_values.get('SerialNumber', 'Unknown'),
                'udid': self.lockdown.udid
            }
            
            self.update_progress(50, 100, f"已連接: {self.device_info['name']}")
            logger.info(f"✓ 已連接設備: {self.device_info['name']}")
            logger.info(f"✓ 型號: {self.device_info['model']}")
            logger.info(f"✓ iOS版本: {self.device_info['ios_version']}")
            
            # 檢查iOS版本相容性
            ios_version = self.device_info['ios_version']
            if ios_version.startswith('18.'):
                logger.info("✓ 檢測到iOS 18，使用相容模式")
            elif ios_version.startswith(('17.', '16.', '15.')):
                logger.info(f"✓ iOS {ios_version}，使用標準模式")
            else:
                logger.warning(f"⚠ iOS {ios_version}，可能需要特殊處理")
            
            self.update_progress(100, 100, "設備連接完成")
            return True
                
        except Exception as e:
            logger.error(f"✗ 連接設備失敗: {e}")
            self.update_progress(0, 100, f"連接失敗: {str(e)}")
            logger.error("請確認:")
            logger.error("1. iPhone已透過USB連接")
            logger.error("2. iPhone上選擇了「信任此電腦」")
            logger.error("3. iPhone處於解鎖狀態")
            logger.error("4. 嘗試重新插拔USB線")
            return False
    
    def setup_afc_service(self):
        """設定AFC服務"""
        if self.is_stopped():
            return False
            
        try:
            self.update_progress(0, 100, "正在初始化AFC服務...")
            
            self.afc = AfcService(self.lockdown)
            
            # 檢測AFC API版本並記錄可用方法
            self._detect_afc_api_version()
            
            # 測試AFC服務是否正常工作
            try:
                # 嘗試列出根目錄來測試連接
                test_items = self.safe_listdir('/')
                if test_items is not None:
                    logger.info("✓ AFC服務已啟動並測試成功")
                    self.update_progress(100, 100, "AFC服務已啟動")
                    return True
                else:
                    logger.error("✗ AFC服務啟動但無法訪問文件系統")
                    return False
                    
            except Exception as test_error:
                logger.error(f"✗ AFC服務測試失敗: {test_error}")
                return False
                
        except Exception as e:
            logger.error(f"✗ AFC服務啟動失敗: {e}")
            self.update_progress(0, 100, f"AFC服務失敗: {str(e)}")
            return False
    
    def _detect_afc_api_version(self):
        """檢測AFC API版本和可用方法"""
        available_methods = []
        
        # 檢測文件讀取方法
        if hasattr(self.afc, 'open'):
            available_methods.append('open')
        if hasattr(self.afc, 'file_open'):
            available_methods.append('file_open')
        if hasattr(self.afc, 'get_file_contents'):
            available_methods.append('get_file_contents')
        if hasattr(self.afc, 'pull_file'):
            available_methods.append('pull_file')
        if hasattr(self.afc, 'pull'):
            available_methods.append('pull')
        
        # 檢測目錄操作方法
        if hasattr(self.afc, 'listdir'):
            available_methods.append('listdir')
        if hasattr(self.afc, 'ls'):
            available_methods.append('ls')
        
        logger.info(f"✓ 檢測到AFC API方法: {', '.join(available_methods)}")
        
        if not available_methods:
            logger.warning("⚠ 未檢測到任何可用的AFC API方法")
        
        return available_methods
    
    def safe_listdir(self, directory_path):
        """安全的目錄列表功能，處理各種錯誤和API版本"""
        if self.is_stopped():
            return None
            
        try:
            # 先檢查目錄是否存在
            if not self.afc.exists(directory_path):
                logger.debug(f"目錄不存在: {directory_path}")
                return None
            
            # 檢查是否為目錄
            if not self.afc.isdir(directory_path):
                logger.debug(f"不是目錄: {directory_path}")
                return None
            
            # 嘗試不同的列表方法
            items = None
            
            # 方法1: 標準listdir
            if hasattr(self.afc, 'listdir'):
                try:
                    items = self.afc.listdir(directory_path)
                except Exception as e:
                    logger.debug(f"listdir方法失敗: {e}")
            
            # 方法2: 嘗試ls方法
            if items is None and hasattr(self.afc, 'ls'):
                try:
                    result = self.afc.ls(directory_path)
                    # ls方法可能返回不同格式，需要處理
                    if isinstance(result, list):
                        items = result
                    elif isinstance(result, dict) and 'entries' in result:
                        items = result['entries']
                    else:
                        logger.debug(f"ls方法返回未知格式: {type(result)}")
                except Exception as e:
                    logger.debug(f"ls方法失敗: {e}")
            
            # 方法3: 嘗試list_directory
            if items is None and hasattr(self.afc, 'list_directory'):
                try:
                    items = self.afc.list_directory(directory_path)
                except Exception as e:
                    logger.debug(f"list_directory方法失敗: {e}")
            
            if items is not None:
                # 過濾掉特殊項目
                filtered_items = []
                for item in items:
                    # 跳過特殊目錄項
                    if item not in ['.', '..', '']:
                        # 如果item是字典格式，提取名稱
                        if isinstance(item, dict):
                            if 'name' in item:
                                filtered_items.append(item['name'])
                            elif 'filename' in item:
                                filtered_items.append(item['filename'])
                        else:
                            filtered_items.append(str(item))
                
                return filtered_items
            
            logger.debug(f"所有列表方法都失敗: {directory_path}")
            return None
            
        except AfcError as afc_error:
            logger.debug(f"AFC錯誤，無法訪問目錄 {directory_path}: {afc_error}")
            return None
        except PermissionError:
            logger.debug(f"權限錯誤，無法訪問目錄 {directory_path}")
            return None
        except Exception as e:
            logger.debug(f"其他錯誤，無法訪問目錄 {directory_path}: {e}")
            return None
    
    def get_photo_directories_safe(self):
        """安全的照片目錄搜索"""
        if self.is_stopped():
            return []
        
        # 擴展的iOS照片路徑列表
        potential_paths = [
            # 標準DCIM路徑
            '/DCIM',
            '/Media/DCIM',
            
            # iOS沙盒路徑
            '/var/mobile/Media/DCIM',
            '/var/mobile/Media/PhotoData',
            '/var/mobile/Media/Photos',
            
            # 私有路徑
            '/private/var/mobile/Media/DCIM',
            '/private/var/mobile/Media/PhotoData',
            
            # 其他可能路徑
            '/PhotoData',
            '/Photos',
            '/Media/Photos',
            '/Media/PhotoData',
            
            # 應用程式特定路徑
            '/var/mobile/Applications',
            '/Applications'
        ]
        
        available_paths = []
        total_paths = len(potential_paths)
        
        self.update_progress(0, total_paths, "正在搜索照片目錄...")
        
        for i, path in enumerate(potential_paths):
            if self.is_stopped():
                logger.info("🛑 目錄搜索已中斷")
                break
                
            self.update_progress(i, total_paths, f"檢查: {path}")
            
            items = self.safe_listdir(path)
            if items is not None and len(items) > 0:
                # 檢查是否包含照片相關內容
                photo_related = False
                for item in items[:10]:  # 只檢查前10個項目
                    item_lower = item.lower()
                    if (item_lower.endswith(('.jpg', '.jpeg', '.png', '.heic', '.mov', '.mp4')) or
                        item_lower.startswith(('img_', 'dsc_', '100apple', '101apple', '102apple')) or
                        'apple' in item_lower):
                        photo_related = True
                        break
                
                if photo_related or len(items) > 50:  # 包含照片或項目很多
                    available_paths.append(path)
                    logger.info(f"✓ 找到照片目錄: {path} ({len(items)} 項目)")
        
        self.update_progress(total_paths, total_paths, f"找到 {len(available_paths)} 個可用目錄")
        return available_paths
    
    def scan_photos_safe(self, directory_path, max_depth=3):
        """安全的照片掃描，限制遞歸深度"""
        if max_depth <= 0 or self.is_stopped():
            return []
        
        photos = []
        items = self.safe_listdir(directory_path)
        
        if items is None:
            return photos
        
        # 分離文件和子目錄
        files = []
        subdirs = []
        
        for item in items:
            if self.is_stopped():
                break
                
            item_path = f"{directory_path.rstrip('/')}/{item}"
            
            try:
                if self.afc.isdir(item_path):
                    subdirs.append(item_path)
                else:
                    if self.is_media_file(item):
                        files.append(item_path)
                        self.scan_progress["current"] += 1
                        
                        # 每找到20個文件更新一次進度
                        if self.scan_progress["current"] % 20 == 0:
                            self.update_progress(
                                self.scan_progress["current"], 
                                self.scan_progress["total"], 
                                f"已找到 {self.scan_progress['current']} 個媒體文件"
                            )
            except Exception as e:
                logger.debug(f"處理項目失敗 {item_path}: {e}")
                continue
        
        # 添加當前目錄的文件
        photos.extend(files)
        
        # 處理子目錄（限制數量和深度）
        if subdirs and not self.is_stopped():
            # 限制同時處理的子目錄數量
            max_subdirs = min(20, len(subdirs))
            for subdir in subdirs[:max_subdirs]:
                if self.is_stopped():
                    break
                    
                try:
                    sub_photos = self.scan_photos_safe(subdir, max_depth - 1)
                    photos.extend(sub_photos)
                except Exception as e:
                    logger.debug(f"掃描子目錄失敗 {subdir}: {e}")
                    continue
        
        return photos
    
    def is_media_file(self, filename):
        """檢查是否為媒體文件"""
        media_extensions = {
            # 圖片格式
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
            '.heic', '.heif', '.webp', '.raw', '.dng', '.cr2', '.nef',
            # 影片格式
            '.mov', '.mp4', '.avi', '.mkv', '.m4v', '.3gp', '.wmv',
            '.flv', '.webm', '.mpg', '.mpeg'
        }
        filename_lower = filename.lower()
        return any(filename_lower.endswith(ext) for ext in media_extensions)
    
    def get_file_info_safe(self, file_path):
        """安全獲取文件信息"""
        if self.is_stopped():
            return None
            
        try:
            stat_info = self.afc.stat(file_path)
            return {
                'path': file_path,
                'name': os.path.basename(file_path),
                'size': stat_info.get('st_size', 0),
                'modified': stat_info.get('st_mtime', 0),
                'created': stat_info.get('st_birthtime', 0),
                'type': self.get_file_type(file_path)
            }
        except Exception as e:
            logger.debug(f"獲取文件信息失敗 {file_path}: {e}")
            return None
    
    def get_file_type(self, file_path):
        """判斷文件類型"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.heif', '.webp', '.raw', '.dng']:
            return 'image'
        elif ext in ['.mov', '.mp4', '.avi', '.mkv', '.m4v', '.3gp', '.wmv']:
            return 'video'
        else:
            return 'unknown'
    
    def safe_open_file(self, file_path, mode='rb'):
        """安全的文件打開方法，兼容不同版本的AFC API"""
        try:
            # 嘗試新版本的API
            if hasattr(self.afc, 'open'):
                return self.afc.open(file_path, mode)
            # 嘗試舊版本的API
            elif hasattr(self.afc, 'file_open'):
                return self.afc.file_open(file_path, mode)
            # 嘗試其他可能的方法
            elif hasattr(self.afc, 'get_file_contents'):
                # 這個方法一次性讀取整個文件
                data = self.afc.get_file_contents(file_path)
                # 創建一個類似文件對象的包裝器
                from io import BytesIO
                return BytesIO(data)
            else:
                raise AttributeError("AFC服務不支援文件讀取操作")
                
        except AttributeError as attr_error:
            logger.error(f"AFC API不相容: {attr_error}")
            raise
        except Exception as e:
            logger.error(f"打開文件失敗 {file_path}: {e}")
            raise
    
    def download_file_safe(self, remote_path, local_path, file_info=None):
        """安全的文件下載功能"""
        if self.is_stopped():
            return False
            
        try:
            # 確保本地目錄存在
            local_dir = os.path.dirname(local_path)
            Path(local_dir).mkdir(parents=True, exist_ok=True)
            
            # 檢查文件是否已存在且大小相同
            if os.path.exists(local_path) and file_info:
                local_size = os.path.getsize(local_path)
                remote_size = file_info.get('size', 0)
                if local_size == remote_size and remote_size > 0:
                    logger.debug(f"跳過已存在的文件: {os.path.basename(local_path)}")
                    return True
            
            # 嘗試不同的下載方法
            success = False
            
            # 方法1: 使用安全的文件打開方法
            try:
                success = self._download_with_stream(remote_path, local_path, file_info)
            except Exception as stream_error:
                logger.debug(f"流式下載失敗，嘗試其他方法: {stream_error}")
                
                # 方法2: 嘗試一次性讀取
                try:
                    success = self._download_with_bulk_read(remote_path, local_path, file_info)
                except Exception as bulk_error:
                    logger.debug(f"批量讀取失敗: {bulk_error}")
                    
                    # 方法3: 嘗試使用pull_file（如果可用）
                    try:
                        success = self._download_with_pull(remote_path, local_path, file_info)
                    except Exception as pull_error:
                        logger.error(f"所有下載方法都失敗: 流式={stream_error}, 批量={bulk_error}, 拉取={pull_error}")
                        return False
            
            if success and not self.is_stopped():
                # 驗證下載的文件
                if os.path.exists(local_path):
                    actual_size = os.path.getsize(local_path)
                    expected_size = file_info.get('size', 0) if file_info else 0
                    
                    if expected_size > 0 and actual_size != expected_size:
                        logger.warning(f"文件大小不匹配 {os.path.basename(local_path)}: {actual_size} vs {expected_size}")
                    
                    # 設置文件時間
                    if file_info and file_info.get('modified'):
                        try:
                            os.utime(local_path, (file_info['modified'], file_info['modified']))
                        except:
                            pass
                    
                    logger.info(f"✓ 已下載: {os.path.basename(local_path)} ({actual_size} bytes)")
                    return True
                else:
                    logger.error(f"下載後文件不存在: {local_path}")
                    return False
            
            return success
            
        except Exception as e:
            logger.error(f"✗ 下載失敗 {os.path.basename(remote_path if 'remote_path' in locals() else 'unknown')}: {e}")
            return False
    
    def _download_with_stream(self, remote_path, local_path, file_info):
        """使用流式讀取下載文件"""
        chunk_size = 512 * 1024  # 512KB chunks
        downloaded_size = 0
        total_size = file_info.get('size', 0) if file_info else 0
        
        with self.safe_open_file(remote_path, 'rb') as remote_file:
            with open(local_path, 'wb') as local_file:
                while not self.is_stopped():
                    chunk = remote_file.read(chunk_size)
                    if not chunk:
                        break
                    local_file.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 大文件顯示進度
                    if total_size > 5 * 1024 * 1024:  # 大於5MB
                        progress = (downloaded_size / total_size * 100) if total_size > 0 else 0
                        self.update_progress(
                            downloaded_size, total_size, 
                            f"下載: {os.path.basename(local_path)[:20]}... ({progress:.1f}%)"
                        )
        
        if self.is_stopped():
            if os.path.exists(local_path):
                os.remove(local_path)
            return False
        
        return True
    
    def _download_with_bulk_read(self, remote_path, local_path, file_info):
        """使用一次性讀取下載文件"""
        if hasattr(self.afc, 'get_file_contents'):
            data = self.afc.get_file_contents(remote_path)
            
            if self.is_stopped():
                return False
            
            with open(local_path, 'wb') as local_file:
                local_file.write(data)
            
            return True
        else:
            raise AttributeError("AFC不支援批量讀取")
    
    def _download_with_pull(self, remote_path, local_path, file_info):
        """使用pull_file方法下載（如果可用）"""
        if hasattr(self.afc, 'pull_file'):
            self.afc.pull_file(remote_path, local_path)
            return not self.is_stopped()
        elif hasattr(self.afc, 'pull'):
            self.afc.pull(remote_path, local_path)
            return not self.is_stopped()
        else:
            raise AttributeError("AFC不支援pull操作")
    
    def download_photos_batch_safe(self, photos_info, output_directory="./iphone_photos"):
        """安全的批量下載"""
        if not photos_info:
            logger.warning("沒有照片需要下載")
            return 0, 0
        
        total_photos = len(photos_info)
        downloaded_count = 0
        failed_count = 0
        
        logger.info(f"開始下載 {total_photos} 個文件...")
        self.update_progress(0, total_photos, "準備下載...")
        
        # 順序下載而非並行，提高穩定性
        for i, photo_info in enumerate(photos_info):
            if self.is_stopped():
                logger.info("🛑 下載已中斷")
                break
            
            relative_path = photo_info['path'].lstrip('/')
            local_path = os.path.join(output_directory, relative_path)
            
            # 顯示當前下載進度
            self.update_progress(
                i, total_photos, 
                f"下載中: {os.path.basename(photo_info['path'])[:30]}..."
            )
            
            if self.download_file_safe(photo_info['path'], local_path, photo_info):
                downloaded_count += 1
            else:
                failed_count += 1
            
            # 每10個文件顯示一次總進度
            if (i + 1) % 10 == 0:
                completed = downloaded_count + failed_count
                success_rate = (downloaded_count / completed * 100) if completed > 0 else 0
                logger.info(f"進度: {completed}/{total_photos} (成功率: {success_rate:.1f}%)")
        
        return downloaded_count, failed_count
    
    def analyze_photos_safe(self):
        """安全的照片分析"""
        self.reset()
        
        if not self.connect_device():
            return None
        
        if self.is_stopped():
            return None
        
        if not self.setup_afc_service():
            return None
        
        if self.is_stopped():
            return None
        
        logger.info("正在分析照片庫...")
        self.update_progress(0, 100, "開始分析照片庫...")
        
        # 獲取照片目錄
        directories = self.get_photo_directories_safe()
        
        if self.is_stopped():
            logger.info("🛑 照片庫分析已中斷")
            return None
        
        if not directories:
            logger.warning("未找到任何可訪問的照片目錄")
            return None
        
        # 掃描所有照片
        all_photos = []
        self.scan_progress = {"current": 0, "total": 0, "message": "掃描中..."}
        
        for i, directory in enumerate(directories):
            if self.is_stopped():
                logger.info("🛑 目錄掃描已中斷")
                break
                
            logger.info(f"掃描目錄: {directory} ({i+1}/{len(directories)})")
            self.update_progress(i * 50, len(directories) * 50, f"掃描目錄: {directory}")
            
            photos = self.scan_photos_safe(directory)
            
            if self.is_stopped():
                break
            
            # 順序獲取文件信息（避免並行造成的穩定性問題）
            if photos:
                logger.info(f"獲取 {len(photos)} 個文件的詳細信息...")
                
                for j, photo in enumerate(photos):
                    if self.is_stopped():
                        break
                    
                    photo_info = self.get_file_info_safe(photo)
                    if photo_info:
                        all_photos.append(photo_info)
                    
                    # 每50個文件更新進度
                    if (j + 1) % 50 == 0:
                        self.update_progress(
                            j + 1, len(photos),
                            f"已處理 {j + 1}/{len(photos)} 個文件"
                        )
        
        if self.is_stopped():
            logger.info("🛑 照片庫分析已中斷")
            if all_photos:
                logger.info(f"⚠️  已分析 {len(all_photos)} 個文件 (部分結果)")
            return None
        
        # 統計分析
        if all_photos:
            total_size = sum(p['size'] for p in all_photos)
            image_count = len([p for p in all_photos if p['type'] == 'image'])
            video_count = len([p for p in all_photos if p['type'] == 'video'])
            
            analysis = {
                'total_files': len(all_photos),
                'image_count': image_count,
                'video_count': video_count,
                'total_size_mb': total_size / (1024 * 1024),
                'photos_info': all_photos
            }
            
            self.update_progress(100, 100, "分析完成")
            logger.info(f"✓ 分析完成:")
            logger.info(f"  總文件數: {analysis['total_files']}")
            logger.info(f"  照片: {image_count}, 影片: {video_count}")
            logger.info(f"  總大小: {analysis['total_size_mb']:.1f} MB")
            
            return analysis
        
        logger.warning("未找到任何媒體文件")
        return None
    
    def interactive_download_safe(self):
        """安全的互動式下載介面"""
        print("\n💡 使用提示: 操作過程中隨時按 Ctrl+C 可以中斷操作")
        print("🔧 此版本針對穩定性進行優化，使用順序處理模式\n")
        
        def progress_callback(current, total, message):
            if total > 0:
                percentage = (current / total) * 100
                print(f"\r⏳ {message} [{current}/{total}] {percentage:.1f}%", end='', flush=True)
            else:
                print(f"\r⏳ {message}", end='', flush=True)
        
        self.set_progress_callback(progress_callback)
        
        print("🔍 開始分析iPhone照片庫...")
        analysis = self.analyze_photos_safe()
        
        if not analysis:
            if self.is_stopped():
                print("\n🛑 分析已中斷")
            else:
                print("\n❌ 無法分析照片庫或未找到媒體文件")
                print("建議:")
                print("1. 確認iPhone上有照片")
                print("2. 檢查iPhone信任設定")
                print("3. 嘗試重新連接設備")
            return
        
        print(f"\n\n📱 發現 {analysis['total_files']} 個媒體文件")
        print(f"📷 照片: {analysis['image_count']} 個")
        print(f"🎬 影片: {analysis['video_count']} 個")
        print(f"💾 總大小: {analysis['total_size_mb']:.1f} MB")
        
        while True:
            if self.is_stopped():
                print("\n🛑 操作已中斷")
                break
                
            print("\n選擇下載選項:")
            print("1. 下載所有文件")
            print("2. 只下載照片")
            print("3. 只下載影片")
            print("4. 重新分析")
            print("5. 退出")
            
            try:
                choice = input("\n請選擇 (1-5): ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n🛑 操作已中斷")
                break
            
            if choice == '1':
                photos_to_download = analysis['photos_info']
            elif choice == '2':
                photos_to_download = [p for p in analysis['photos_info'] if p['type'] == 'image']
            elif choice == '3':
                photos_to_download = [p for p in analysis['photos_info'] if p['type'] == 'video']
            elif choice == '4':
                print("\n🔄 重新分析照片庫...")
                analysis = self.analyze_photos_safe()
                if not analysis:
                    print("❌ 重新分析失敗")
                continue
            elif choice == '5':
                break
            else:
                print("❌ 無效選擇")
                continue
            
            if not photos_to_download:
                print("⚠️  沒有符合條件的文件")
                continue
            
            try:
                output_dir = input(f"輸出目錄 (預設: ./iphone_photos): ").strip()
                if not output_dir:
                    output_dir = "./iphone_photos"
            except (KeyboardInterrupt, EOFError):
                print("\n🛑 操作已中斷")
                break
            
            print(f"\n🚀 開始下載 {len(photos_to_download)} 個文件...")
            print("💡 按 Ctrl+C 可隨時中斷下載")
            print("⚠️  使用穩定模式，速度較慢但更可靠")
            
            start_time = time.time()
            self.reset()
            
            downloaded, failed = self.download_photos_batch_safe(photos_to_download, output_dir)
            
            elapsed_time = time.time() - start_time
            
            if self.is_stopped():
                print(f"\n\n🛑 下載已中斷!")
                print(f"✓ 已完成: {downloaded} 個文件")
                print(f"✗ 失敗: {failed} 個文件")
                print(f"⏱ 耗時: {elapsed_time:.1f} 秒")
            else:
                print(f"\n\n🎉 下載完成!")
                print(f"✓ 成功: {downloaded} 個文件")
                print(f"✗ 失敗: {failed} 個文件")
                print(f"⏱ 耗時: {elapsed_time:.1f} 秒")
                
                if failed > 0:
                    print(f"💡 有 {failed} 個文件下載失敗，可能原因:")
                    print("   - 文件被系統保護")
                    print("   - 網路連接問題") 
                    print("   - 存儲空間不足")
            
            try:
                continue_choice = input("\n是否繼續其他操作? (y/n): ").strip().lower()
                if continue_choice != 'y':
                    break
            except (KeyboardInterrupt, EOFError):
                print("\n🛑 操作已中斷")
                break
            
            self.reset()

def main():
    """主程式"""
    print("🍎 iPhone 15 Pro Max 照片讀取程式 (穩定版)")
    print("🔧 專為iOS 18.5優化，修正模組相容性問題")
    print("=" * 60)
    
    reader = SafeiPhonePhotoReader()
    
    try:
        reader.interactive_download_safe()
    except KeyboardInterrupt:
        print("\n\n🛑 程式已中斷")
        print("感謝使用!")
    except Exception as e:
        logger.error(f"程式執行錯誤: {e}")
        print(f"\n❌ 發生錯誤: {e}")
        print("請檢查日誌文件: iphone_reader.log")
        print("\n故障排除建議:")
        print("1. 確認iPhone已連接並信任此電腦")
        print("2. 嘗試重新啟動iPhone和電腦")
        print("3. 更新pymobiledevice3: pip install --upgrade pymobiledevice3")
        print("4. 檢查USB線和連接埠")

if __name__ == "__main__":
    main()