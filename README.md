## 一个github actions自动代理爬取仓库

每天北京时间10-12点运行一次

### actions当前状态

![Proxy Pool Update](https://github.com/LiMingda-101212/Proxy-Pool/actions/workflows/proxy-crawler.yml/badge.svg)

### 介绍

代理池文件(csv)介绍：

```
类型,代理,分数,是否支持中国,是否支持国际,是否为透明代理,识别到的ip
Type,Proxy:Port,Score,,China,International,Transparent,DetectedIP
```
支持http/socks4/socks5

#### 功能介绍:
本程序用于代理管理,有以下几个功能:
1. 加载和验证新代理,可从爬虫(自动),本地文件(用于手动添加代理时使用,可以选择代理类型(这样比较快),也可用自动检测(若用自动检测可能较慢))加载,并将通过的代理添加到代理池文件(OUTPUT_FILE).新代理使用自动检测类型或指定类型.
  在验证之前会先将重复代理,错误代理筛除,确保不做无用功.满分100分,新代理只要通过百度或Google任一验证就98分,错误代理和无效代理0分(会被0分清除函数清除).支持透明代理检测功能，识别会泄露真实IP的代理.
  有中断恢复功能,当验证过程被中断时,会自动保存已完成的代理到代理池,未完成的代理保存到中断文件,下次可选择继续验证

2. 检验和更新代理池内代理的有效性,使用代理池文件中的Type作为类型,最后两个分别是是否支持国内和国外,再次验证成功一个(国内/国外)加1分,全成功加2分,无效代理和错误代理减1分,更直观的分辨代理的稳定性.
  支持透明代理检测功能，识别会泄露真实IP的代理.有中断恢复功能,当验证过程被中断时,会自动保存已完成的代理到代理池,未完成的代理保存到中断文件,下次可选择继续验证

3. 提取指定数量的代理,优先提取分数高,稳定的代理,可指定提取类型,支持范围和是否为透明代理
4. 查看代理池状态(总代理数量,各种类型代理的分数分布情况,支持范围统计)
5. 支持透明代理检测功能，识别会泄露真实IP的代理

### 快速开始

本地使用:

下方程序功能完善,完全可以本地使用

```python

import re
import requests
import concurrent.futures
import time
import os
import sys
import csv
import signal

# ============默认配置区 - Default Configuration
OUTPUT_FILE = "../ProxyPool/proxies.csv"  # 输出有效代理文件（CSV格式）- Export valid proxy file (CSV format)
TEST_URL_CN = "http://www.baidu.com"  # 国内测试URL - Domestic test URL
TEST_URL_INTL = "http://www.google.com"  # 国际测试URL - International test URL
TRANSPARENT_CHECK_URL = "http://httpbin.org/ip"  # 透明代理检测URL
TIMEOUT_CN = 6  # 国内测试超时时间(秒) - Domestic test timeout (s)
TIMEOUT_INTL = 10  # 国际测试超时时间(秒) - International test timeout (s)
TRANSPARENT_TIMEOUT = 8  # 透明代理检测超时时间(秒)
MAX_WORKERS = 100  # 最大并发数 - Maximum concurrency
MAX_SCORE = 100  # 最大积分 - Maximum score

# 中断恢复相关配置
INTERRUPT_DIR = "../ProxyPool/interrupt"  # 中断文件目录
INTERRUPT_FILE = os.path.join(INTERRUPT_DIR, "interrupted_proxies.csv")  # 爬取验证中断文件
INTERRUPT_FILE_LOAD = os.path.join(INTERRUPT_DIR, "interrupted_load_proxies.csv")   # 本地文件加载中断文件
INTERRUPT_FILE_EXISTING = os.path.join(INTERRUPT_DIR, "interrupted_existing_proxies.csv")   # 更新代理池中断文件

# 全局变量用于中断处理
current_validation_process = None
interrupted = False

# 爬取参数
HEADERS = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0'
}

def create_interrupt_dir():
    """创建中断目录"""
    os.makedirs(INTERRUPT_DIR, exist_ok=True)

def save_interrupted_proxies(remaining_proxies, proxy_type, original_count, interrupt_file=INTERRUPT_FILE):
    """保存中断时的代理列表"""
    create_interrupt_dir()
    with open(interrupt_file, 'w', encoding="utf-8", newline='') as file:
        writer = csv.writer(file)
        writer.writerow([proxy_type, original_count])  # 第一行保存类型和原始数量
        for proxy in remaining_proxies:
            writer.writerow([proxy])

def load_interrupted_proxies(interrupt_file=INTERRUPT_FILE):
    """加载中断的代理列表"""
    # 如果没有中断记录
    if not os.path.exists(interrupt_file):
        return None, None, None
    
    try:
        with open(interrupt_file, 'r', encoding="utf-8") as file:
            reader = csv.reader(file)
            first_row = next(reader, None)
            # 如果无效
            if not first_row or len(first_row) < 2:
                return None, None, None
            
            proxy_type = first_row[0]
            original_count = int(first_row[1])
            remaining_proxies = [row[0] for row in reader if row]
        # 有效并成功读取  
        return remaining_proxies, proxy_type, original_count  # 剩余代理,类型,原始数量
    # 失败
    except:
        return None, None, None

def delete_interrupt_file(interrupt_file=INTERRUPT_FILE):
    """删除中断文件"""
    if os.path.exists(interrupt_file):
        os.remove(interrupt_file)

def signal_handler(signum, frame):
    """信号处理函数，用于捕获Ctrl+C"""
    global interrupted
    interrupted = True
    print("\n\n⚠️ 检测到中断信号，正在保存进度...")

def setup_interrupt_handler():
    """设置中断处理器"""
    global interrupted
    interrupted = False
    signal.signal(signal.SIGINT, signal_handler)

class ProxyScraper:
    """
    get ip

    :param url: 请求地址
    :param regex_pattern: re解析式，用于解析爬取结果
    :param capture_groups: 要返回的re中的值，[IpName,Port]
    :return: [proxy:port]
    """
    def __init__(self, url: str, regex_pattern: str, capture_groups: list):
        self.url = url
        self.encoding = "utf-8"
        self.regex_pattern = regex_pattern
        self.capture_groups = capture_groups

    def scrape_proxies(self):
        extracted_data = []
        try:
            response = requests.get(url=self.url, headers=HEADERS, timeout=TIMEOUT_CN)
            if response.status_code == 200:  # 判断状态码
                response.encoding = self.encoding  # 使用utf-8
                regex = re.compile(self.regex_pattern, re.S)  # 创建一个re对象
                matches = regex.finditer(response.text)  # 对获取的东西进行解析
                for match in matches:
                    for group_name in self.capture_groups:  # 依次输出参数capture_groups中的指定内容
                        extracted_data.append(f"{match.group(group_name)}")
                proxy_list = [f"{extracted_data[i].strip()}:{extracted_data[i + 1].strip()}" for i in
                            range(0, len(extracted_data), 2)]  # 整合列表为[proxy:port]
                response.close()
                return proxy_list
            else:
                get_error = f"\n爬取失败，❌ 状态码{response.status_code}"   # 前面的\n防止与进度条混在一行
                print(get_error)
                return get_error

        except Exception as e:
            get_error = f"\n爬取失败，❌ 错误: {str(e)}"
            print(get_error)
            return get_error

def get_own_ip():
    """获取自己的公网IP地址"""
    try:
        response = requests.get(TRANSPARENT_CHECK_URL, timeout=TRANSPARENT_TIMEOUT)
        if response.status_code == 200:
            return response.json()['origin']
    except Exception as e:
        print(f"获取本机IP失败: {str(e)}")
    return None

def check_transparent_proxy(proxy, proxy_type="http", own_ip=None):
    """
    检测代理是否为透明代理
    
    :param proxy: 代理地址
    :param proxy_type: 代理类型
    :param own_ip: 自己的公网IP（可选）
    :return: (是否为透明代理, 检测到的IP)
    """
    if own_ip is None:
        own_ip = get_own_ip()
        if own_ip is None:
            return False, "unknown"  # 无法获取本机IP，跳过透明代理检测
    
    try:
        # 设置代理
        if proxy_type == "http":
            proxies_config = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}"
            }
        elif proxy_type == "socks4":
            proxies_config = {
                "http": f"socks4://{proxy}",
                "https": f"socks4://{proxy}"
            }
        elif proxy_type == "socks5":
            proxies_config = {
                "http": f"socks5://{proxy}",
                "https": f"socks5://{proxy}"
            }
        else:
            proxies_config = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}"
            }
        
        # 使用代理访问检测网站
        response = requests.get(
            TRANSPARENT_CHECK_URL,
            proxies=proxies_config,
            timeout=TRANSPARENT_TIMEOUT
        )
        
        if response.status_code == 200:
            proxy_ip_data = response.json()
            proxy_ip = proxy_ip_data['origin']
            
            # 判断是否为透明代理：如果返回的IP包含真实IP，则为透明代理
            is_transparent = own_ip in proxy_ip
            
            return is_transparent, proxy_ip
        else:
            return False, "unknown"
            
    except Exception as e:
        return False, "unknown"

def check_proxy_single(proxy, test_url, timeout=TIMEOUT_CN, 
                      retries=1, proxy_type="auto"):
    """
    检查单个代理IP对单个URL的可用性（支持HTTP和SOCKS）
    
    :param proxy_type: 代理类型 - "auto"(自动检测), "http", "socks4", "socks5"
    :param proxy: 代理IP地址和端口 (格式: ip:port)
    :param test_url: 用于测试的URL
    :param timeout: 请求超时时间(秒)
    :param retries: 重试次数
    :return: 是否可用, 响应时间, 检测到的类型
    """
    # 根据代理类型设置proxies字典
    if proxy_type == "auto":
        # 自动检测：先尝试HTTP，再尝试SOCKS5，最后SOCKS4
        protocols_to_try = ["http", "socks5", "socks4"]
    else:
        # 指定类型时，只尝试该类型
        protocols_to_try = [proxy_type]
    
    detected_type = proxy_type if proxy_type != "auto" else "unknown"
    
    for current_protocol in protocols_to_try:
        if current_protocol == "http":
            proxies_config = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}"
            }
        elif current_protocol == "socks4":
            proxies_config = {
                "http": f"socks4://{proxy}",
                "https": f"socks4://{proxy}"
            }
        elif current_protocol == "socks5":
            proxies_config = {
                "http": f"socks5://{proxy}",
                "https": f"socks5://{proxy}"
            }
        else:
            continue

        for attempt in range(retries):
            try:
                start_time = time.time()
                response = requests.get(
                    test_url,
                    proxies=proxies_config,
                    timeout=timeout,
                    allow_redirects=False
                )
                end_time = time.time()
                response_time = end_time - start_time

                if response_time > timeout:
                    # 超时，继续下一个协议（如果是自动检测）
                    break

                if response.status_code == 200:
                    detected_type = current_protocol
                    return True, response_time, detected_type
                    
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(0.5)
                    continue
                # 当前协议失败，如果是自动检测则尝试下一个协议
                break
                
    # 如果是指定类型验证失败，返回指定类型（即使失败）
    if proxy_type != "auto":
        detected_type = proxy_type
    
    return False, None, detected_type

def check_proxy_dual(proxy, proxy_type="auto", check_transparent=False):
    """
    双重验证代理：同时验证百度(国内)和Google(国际)，可选透明代理检测
    
    :return: (是否通过国内, 是否通过国际, 最终检测类型, 是否为透明代理, 检测到的IP)
    """
    # 验证国内网站
    cn_success, cn_response_time, detected_type_cn = check_proxy_single(
        proxy, TEST_URL_CN, TIMEOUT_CN, 1, proxy_type
    )
    
    # 验证国际网站  
    intl_success, intl_response_time, detected_type_intl = check_proxy_single(
        proxy, TEST_URL_INTL, TIMEOUT_INTL, 1, proxy_type
    )
    
    # 使用第一个成功的检测类型，或者第一个检测类型
    final_type = detected_type_cn if detected_type_cn != "unknown" else detected_type_intl
    if final_type == "unknown":
        final_type = proxy_type if proxy_type != "auto" else "http"
    
    # 透明代理检测（只在代理有效且需要检测时进行）
    is_transparent = False
    detected_ip = "unknown"
    
    if check_transparent and (cn_success or intl_success):
        is_transparent, detected_ip = check_transparent_proxy(proxy, final_type)
    
    return cn_success, intl_success, final_type, is_transparent, detected_ip

def check_proxies_batch(proxies, proxy_types, max_workers=MAX_WORKERS, check_type="new", check_transparent=True):
    """
    批量检查代理IP列表（双重验证 + 透明代理检测）
    
    :param proxies: 代理字典 {proxy: score}
    :param proxy_types: 代理类型字典 {proxy: type}
    :param check_type: "new" 新代理 / "existing" 已有代理
    :param check_transparent: 是否进行透明代理检测
    """
    global interrupted
    
    updated_proxies = {}
    updated_types = {}
    updated_china = {}
    updated_international = {}
    updated_transparent = {}
    updated_detected_ips = {}

    # 预先获取本机IP用于透明代理检测
    own_ip = get_own_ip() if check_transparent else None
    if check_transparent and own_ip is None:
        print("⚠️  无法获取本机IP，跳过透明代理检测")
        check_transparent = False

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {}
        for proxy in proxies:
            if interrupted:
                break
                
            # 对于已有代理，使用文件中记录的类型；对于新代理，先看是否指定,否则使用自动检测
            if check_type == "existing" and proxy in proxy_types:
                proxy_type = proxy_types[proxy]
            else:
                proxy_type = proxy_types.get(proxy, "auto")  # 从传入的类型字典获取
                
            future = executor.submit(check_proxy_dual, proxy, proxy_type, check_transparent)
            future_to_proxy[future] = proxy

        for future in concurrent.futures.as_completed(future_to_proxy):
            if interrupted:
                # 取消所有未完成的任务
                for f in future_to_proxy:
                    f.cancel()
                break
                
            proxy = future_to_proxy[future]
            try:
                cn_success, intl_success, detected_type, is_transparent, detected_ip = future.result()

                # 计算分数和更新逻辑
                current_score = proxies.get(proxy, 0)
                
                if check_type == "new":
                    # 新代理：只要通过任一测试就98分
                    if cn_success or intl_success:
                        updated_proxies[proxy] = 98
                        # 透明代理警告
                        transparent_warning = " ⚠️ 透明代理" if is_transparent else ""
                        print(f"✅ 代理有效({detected_type}): {proxy} | 国内: {'✓' if cn_success else '✗'} 国际: {'✓' if intl_success else '✗'}{transparent_warning}")
                    else:
                        updated_proxies[proxy] = 0
                        print(f"❌ 代理无效: {proxy}")
                else:
                    # 已有代理：根据测试结果调整分数
                    if cn_success and intl_success:
                        # 两次都通过，加2分
                        updated_proxies[proxy] = min(current_score + 2, MAX_SCORE)
                        transparent_warning = " ⚠️ 透明代理" if is_transparent else ""
                        print(f"✅ 代理有效({detected_type}): {proxy} | 国内: ✓ 国际: ✓ | 分数: {current_score} -> {updated_proxies[proxy]}{transparent_warning}")
                    elif cn_success or intl_success:
                        # 只通过一个，加1分
                        updated_proxies[proxy] = min(current_score + 1, MAX_SCORE)
                        status = "国内: ✓ 国际: ✗" if cn_success else "国内: ✗ 国际: ✓"
                        transparent_warning = " ⚠️ 透明代理" if is_transparent else ""
                        print(f"🟡 代理部分有效({detected_type}): {proxy} | {status} | 分数: {current_score} -> {updated_proxies[proxy]}{transparent_warning}")
                    else:
                        # 两个都不通过，减1分
                        updated_proxies[proxy] = max(0, current_score - 1)
                        print(f"❌ 代理无效({detected_type}): {proxy} | 国内: ✗ 国际: ✗ | 分数: {current_score} -> {updated_proxies[proxy]}")
                
                # 记录类型和支持范围
                updated_types[proxy] = detected_type
                updated_china[proxy] = cn_success
                updated_international[proxy] = intl_success
                updated_transparent[proxy] = is_transparent
                updated_detected_ips[proxy] = detected_ip
                        
            except Exception as e:
                if not interrupted:  # 只有不是中断引起的异常才打印
                    print(f"❌ 错误代理: {proxy} - {str(e)}")
                
                if check_type == "existing" and proxy in proxies:
                    updated_proxies[proxy] = max(0, proxies[proxy] - 1)
                else:
                    updated_proxies[proxy] = 0
                
                updated_types[proxy] = proxy_types.get(proxy, "http")
                updated_china[proxy] = False
                updated_international[proxy] = False
                updated_transparent[proxy] = False
                updated_detected_ips[proxy] = "unknown"
                    
    return updated_proxies, updated_types, updated_china, updated_international, updated_transparent, updated_detected_ips

def load_proxies_from_file(file_path):
    """从CSV文件加载代理列表、类型、分数、支持范围和透明代理信息"""
    proxies = {}
    proxy_types = {}
    china_support = {}
    international_support = {}
    transparent_proxies = {}
    detected_ips = {}
    
    if not os.path.exists(file_path):
        return proxies, proxy_types, china_support, international_support, transparent_proxies, detected_ips

    with open(file_path, 'r', encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) >= 7:
                # 类型,proxy:port,分数,China,International,Transparent,DetectedIP
                proxy_type = row[0].strip().lower()
                proxy = row[1].strip()
                try:
                    score = int(row[2])
                    china = row[3].strip().lower() == 'true'
                    international = row[4].strip().lower() == 'true'
                    transparent = row[5].strip().lower() == 'true'
                    detected_ip = row[6].strip() if len(row) > 6 else "unknown"
                    
                    proxies[proxy] = score
                    proxy_types[proxy] = proxy_type
                    china_support[proxy] = china
                    international_support[proxy] = international
                    transparent_proxies[proxy] = transparent
                    detected_ips[proxy] = detected_ip
                except:
                    # 如果解析失败，使用默认值
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
            elif len(row) >= 5:
                # 旧格式兼容：类型,proxy:port,分数,China,International（默认非透明代理）
                proxy_type = row[0].strip().lower()
                proxy = row[1].strip()
                try:
                    score = int(row[2])
                    china = row[3].strip().lower() == 'true'
                    international = row[4].strip().lower() == 'true'
                    
                    proxies[proxy] = score
                    proxy_types[proxy] = proxy_type
                    china_support[proxy] = china
                    international_support[proxy] = international
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
            elif len(row) >= 3:
                # 更旧格式兼容：类型,proxy:port,分数（默认不支持任何范围，非透明代理）
                proxy_type = row[0].strip().lower()
                proxy = row[1].strip()
                try:
                    score = int(row[2])
                    proxies[proxy] = score
                    proxy_types[proxy] = proxy_type
                    china_support[proxy] = False
                    international_support[proxy] = False
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
            elif len(row) >= 2:
                # 最旧格式兼容：proxy:port,分数（默认HTTP类型，不支持任何范围，非透明代理）
                proxy = row[0].strip()
                try:
                    score = int(row[1])
                    proxies[proxy] = score
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
                    transparent_proxies[proxy] = False
                    detected_ips[proxy] = "unknown"
    
    return proxies, proxy_types, china_support, international_support, transparent_proxies, detected_ips

def save_valid_proxies(proxies, proxy_types, china_support, international_support, transparent_proxies, detected_ips, file_path):
    """保存有效代理到CSV文件（带类型、分数、支持范围和透明代理信息）"""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    with open(file_path, 'w', encoding="utf-8", newline='') as file:
        writer = csv.writer(file)
        for proxy, score in proxies.items():
            if len(proxy) > 6 and score > 0:  # 基本验证
                proxy_type = proxy_types.get(proxy, "http")
                china = china_support.get(proxy, False)
                international = international_support.get(proxy, False)
                transparent = transparent_proxies.get(proxy, False)
                detected_ip = detected_ips.get(proxy, "unknown")
                writer.writerow([proxy_type, proxy, score, china, international, transparent, detected_ip])

def update_proxy_scores(file_path):
    """更新代理分数文件，移除0分代理"""
    proxies, proxy_types, china_support, international_support, transparent_proxies, detected_ips = load_proxies_from_file(file_path)
    valid_proxies = {k: v for k, v in proxies.items() if v > 0}
    valid_types = {k: v for k, v in proxy_types.items() if k in valid_proxies}
    valid_china = {k: v for k, v in china_support.items() if k in valid_proxies}
    valid_international = {k: v for k, v in international_support.items() if k in valid_proxies}
    valid_transparent = {k: v for k, v in transparent_proxies.items() if k in valid_proxies}
    valid_detected_ips = {k: v for k, v in detected_ips.items() if k in valid_proxies}
    
    save_valid_proxies(valid_proxies, valid_types, valid_china, valid_international, valid_transparent, valid_detected_ips, file_path)
    return len(proxies) - len(valid_proxies)

def filter_proxies(all_proxies):
        """
        从新获取代理中去掉无效的,重复的
        :all_proxies: 新代理列表
        :return: 筛选后的代理列表
        """
        # 进行筛选
        existing_proxies = []
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE,'r') as file:
                csv_reader  = csv.reader(file)
                for row in csv_reader:
                    if len(row) >= 2:
                        existing_proxies.append(row[1])

        new_proxies = []
        duplicate_count = 0
        invalid_count = 0

        for proxy in all_proxies:
            try:
                if (proxy in existing_proxies) or (proxy in new_proxies):
                    print(f'⭕️ 已有代理: {proxy}')
                    duplicate_count += 1
                elif (':' in proxy) and (proxy not in new_proxies):
                    new_proxies.append(proxy)
                    
                else:
                    print(f'❌ 格式无效: {proxy}')
                    invalid_count += 1
            except:
                invalid_count += 1

        print(f'新代理:{len(new_proxies)},已有(重复):{duplicate_count},无效:{invalid_count}')
        return new_proxies

def validate_new_proxies_with_interrupt(new_proxies, proxy_type="auto", from_interrupt=False, source="crawl", check_transparent=True):
    """验证新代理（支持中断恢复和透明代理检测）"""
    global interrupted
    
    if not new_proxies:
        print("没有代理需要验证")
        return

    # 根据来源选择中断文件
    interrupt_file = INTERRUPT_FILE if source == "crawl" else INTERRUPT_FILE_LOAD
    
    original_count = len(new_proxies)
    print(f"共加载 {original_count} 个新代理，使用{proxy_type}类型开始双重测试...")
    if check_transparent:
        print("🔍 启用透明代理检测")
    
    # 保存初始状态到中断文件（如果不是从中断恢复的）
    if not from_interrupt:
        save_interrupted_proxies(new_proxies, proxy_type, original_count, interrupt_file)
        print(f"📁 已创建中断恢复文件: {interrupt_file}")
    
    # 设置中断处理器
    setup_interrupt_handler()
    
    # 新代理初始分数为0
    new_proxies_dict = {proxy: 0 for proxy in new_proxies}
    new_types_dict = {proxy: proxy_type for proxy in new_proxies}
    
    try:
        updated_proxies, updated_types, updated_china, updated_international, updated_transparent, updated_detected_ips = check_proxies_batch(
            new_proxies_dict, new_types_dict, MAX_WORKERS, check_type="new", check_transparent=check_transparent
        )
        
        if interrupted:
            # 计算剩余未验证的代理
            verified_proxies = set(updated_proxies.keys())
            remaining_proxies = [proxy for proxy in new_proxies if proxy not in verified_proxies]
            
            # 保存已验证的代理到代理池
            existing_proxies, existing_types, existing_china, existing_international, existing_transparent, existing_detected_ips = load_proxies_from_file(OUTPUT_FILE)
            for proxy, score in updated_proxies.items():
                if proxy not in existing_proxies or existing_proxies[proxy] < score:
                    existing_proxies[proxy] = score
                    existing_types[proxy] = updated_types[proxy]
                    existing_china[proxy] = updated_china[proxy]
                    existing_international[proxy] = updated_international[proxy]
                    existing_transparent[proxy] = updated_transparent[proxy]
                    existing_detected_ips[proxy] = updated_detected_ips[proxy]

            save_valid_proxies(existing_proxies, existing_types, existing_china, existing_international, existing_transparent, existing_detected_ips, OUTPUT_FILE)
            
            # 更新中断文件
            if remaining_proxies:
                save_interrupted_proxies(remaining_proxies, proxy_type, original_count, interrupt_file)
                print(f"\n⏸️ 验证已中断！已保存 {len(verified_proxies)} 个代理到代理池，剩余 {len(remaining_proxies)} 个代理待验证")
                print(f"📁 中断文件已更新: {interrupt_file}")
            else:
                delete_interrupt_file(interrupt_file)
                print(f"\n✅ 验证完成！所有代理已验证并保存")
                
            interrupted = False
            return
        
        # 正常完成验证
        # 合并到现有代理池
        existing_proxies, existing_types, existing_china, existing_international, existing_transparent, existing_detected_ips = load_proxies_from_file(OUTPUT_FILE)
        for proxy, score in updated_proxies.items():
            if proxy not in existing_proxies or existing_proxies[proxy] < score:
                existing_proxies[proxy] = score
                existing_types[proxy] = updated_types[proxy]
                existing_china[proxy] = updated_china[proxy]
                existing_international[proxy] = updated_international[proxy]
                existing_transparent[proxy] = updated_transparent[proxy]
                existing_detected_ips[proxy] = updated_detected_ips[proxy]

        save_valid_proxies(existing_proxies, existing_types, existing_china, existing_international, existing_transparent, existing_detected_ips, OUTPUT_FILE)
        
        # 删除中断文件
        delete_interrupt_file(interrupt_file)
        
        # 统计结果
        success_count = sum(1 for score in updated_proxies.values() if score == 98)
        china_only = sum(1 for proxy in updated_proxies if updated_china[proxy] and not updated_international[proxy])
        intl_only = sum(1 for proxy in updated_proxies if not updated_china[proxy] and updated_international[proxy])
        both_support = sum(1 for proxy in updated_proxies if updated_china[proxy] and updated_international[proxy])
        transparent_count = sum(1 for proxy in updated_proxies if updated_transparent[proxy])
        
        print(f"\n✅ 验证完成!")
        print(f"成功代理: {success_count}/{original_count}")
        print(f"仅支持国内: {china_only} | 仅支持国际: {intl_only} | 双支持: {both_support}")
        print(f"⚠️  透明代理: {transparent_count} 个")
        print(f"代理池已更新至: {OUTPUT_FILE}")
        
    except Exception as e:
        if not interrupted:
            print(f"验证过程中发生错误: {str(e)}")

def validate_existing_proxies_with_interrupt(check_transparent=True):
    """验证已有代理池中的代理（支持中断恢复和透明代理检测）"""
    global interrupted
    
    print(f"开始验证已有代理池，文件：{OUTPUT_FILE}...")
    if check_transparent:
        print("🔍 启用透明代理检测")
    
    # 首先检查是否有中断记录
    remaining_proxies, _, original_count = load_interrupted_proxies(INTERRUPT_FILE_EXISTING)
    if remaining_proxies:
        print(f"🔍 发现上次验证中断记录!")
        print(f"   剩余代理: {len(remaining_proxies)}/{original_count} 个")
        print("\n请选择:")
        print("  y: 继续上次验证")
        print("  n: 删除记录并重新验证")
        print("  其他: 返回上级菜单")
        
        choice = input("请选择 (y/n/其他): ").lower().strip()
        
        if choice == 'y':
            print("继续上次验证...")
            proxies_to_validate = remaining_proxies
        elif choice == 'n':
            delete_interrupt_file(INTERRUPT_FILE_EXISTING)
            proxies_to_validate = None  # 重新加载所有代理
        else:
            print("返回上级菜单")
            return
    else:
        proxies_to_validate = None
    
    # 加载代理池（不加载旧的支持范围和透明代理信息，以新验证结果为准）
    all_proxies, proxy_types, _, _, _, _ = load_proxies_from_file(OUTPUT_FILE)
    
    if proxies_to_validate is None:
        # 重新验证所有代理
        proxies_to_validate = list(all_proxies.keys())
        original_count = len(proxies_to_validate)
    
    if not proxies_to_validate:
        print("没有代理需要验证")
        return

    print(f"共加载 {len(proxies_to_validate)} 个代理，开始双重测试...")
    
    # 保存初始状态到中断文件
    save_interrupted_proxies(proxies_to_validate, "already_have", original_count, INTERRUPT_FILE_EXISTING)
    print(f"📁 已创建中断恢复文件: {INTERRUPT_FILE_EXISTING}")
    
    # 设置中断处理器
    setup_interrupt_handler()
    
    try:
        # 从代理池中获取当前分数和类型（不获取旧的支持范围和透明代理信息）
        proxies_dict = {proxy: all_proxies[proxy] for proxy in proxies_to_validate}
        types_dict = {proxy: proxy_types[proxy] for proxy in proxies_to_validate}
        
        updated_proxies, updated_types, updated_china, updated_international, updated_transparent, updated_detected_ips = check_proxies_batch(
            proxies_dict, types_dict, MAX_WORKERS, "existing", check_transparent
        )
        
        if interrupted:
            # 计算剩余未验证的代理
            verified_proxies = set(updated_proxies.keys())
            remaining_proxies = [proxy for proxy in proxies_to_validate if proxy not in verified_proxies]
            
            # 更新已验证的代理分数和支持范围
            for proxy, score in updated_proxies.items():
                all_proxies[proxy] = score
                proxy_types[proxy] = updated_types[proxy]
            
            # 保存更新后的代理池
            save_valid_proxies(all_proxies, proxy_types, updated_china, updated_international, updated_transparent, updated_detected_ips, OUTPUT_FILE)
            
            # 更新中断文件
            if remaining_proxies:
                save_interrupted_proxies(remaining_proxies, "already_have", original_count, INTERRUPT_FILE_EXISTING)
                print(f"\n⏸️ 验证已中断！已更新 {len(verified_proxies)} 个代理，剩余 {len(remaining_proxies)} 个代理待验证")
                print(f"📁 中断文件已更新: {INTERRUPT_FILE_EXISTING}")
            else:
                delete_interrupt_file(INTERRUPT_FILE_EXISTING)
                print(f"\n✅ 验证完成！所有代理已更新")
                
            interrupted = False
            return
        
        # 正常完成验证
        # 更新所有代理分数和支持范围
        for proxy, score in updated_proxies.items():
            all_proxies[proxy] = score
            proxy_types[proxy] = updated_types[proxy]
        
        # 保存更新后的代理池
        save_valid_proxies(all_proxies, proxy_types, updated_china, updated_international, updated_transparent, updated_detected_ips, OUTPUT_FILE)
        
        # 清理0分代理
        removed_count = update_proxy_scores(OUTPUT_FILE)
        
        # 删除中断文件
        delete_interrupt_file(INTERRUPT_FILE_EXISTING)
        
        # 最终统计
        final_proxies, _, final_china, final_international, final_transparent, _ = load_proxies_from_file(OUTPUT_FILE)
        final_count = len(final_proxies)
        
        china_only = sum(1 for proxy in final_proxies if final_china[proxy] and not final_international[proxy])
        intl_only = sum(1 for proxy in final_proxies if not final_china[proxy] and final_international[proxy])
        both_support = sum(1 for proxy in final_proxies if final_china[proxy] and final_international[proxy])
        transparent_count = sum(1 for proxy in final_proxies if final_transparent[proxy])

        print(f"\n验证完成! 剩余有效代理: {final_count}/{original_count}")
        print(f"仅支持国内: {china_only} | 仅支持国际: {intl_only} | 双支持: {both_support}")
        print(f"⚠️  透明代理: {transparent_count} 个")
        print(f"已移除 {original_count - final_count} 个无效代理")
        
    except Exception as e:
        if not interrupted:
            print(f"验证过程中发生错误: {str(e)}")

def extract_proxies_by_type(num, proxy_type="all", china_support=None, international_support=None, transparent_only=None):
    """
    按类型和支持范围提取指定数量的代理，优先提取分高的
    
    :param num: 数量
    :param proxy_type: 代理类型 - "http", "socks4", "socks5", "all"
    :param china_support: 是否支持中国 - True/False/None(不限制)
    :param international_support: 是否支持国际 - True/False/None(不限制)
    :param transparent_only: 是否只提取透明代理 - True/False/None(不限制)
    :return: 代理列表
    """
    proxies, proxy_types, china_support_dict, international_support_dict, transparent_proxies, _ = load_proxies_from_file(OUTPUT_FILE)
    
    # 按类型和支持范围筛选
    filtered_proxies = {}
    for proxy, score in proxies.items():
        # 类型筛选
        if proxy_type != "all" and proxy_types.get(proxy) != proxy_type:
            continue
            
        # 中国支持筛选
        if china_support is not None and china_support_dict.get(proxy, False) != china_support:
            continue
            
        # 国际支持筛选
        if international_support is not None and international_support_dict.get(proxy, False) != international_support:
            continue
            
        # 透明代理筛选
        if transparent_only is not None and transparent_proxies.get(proxy, False) != transparent_only:
            continue
            
        filtered_proxies[proxy] = score

    # 按分数降序排序
    sorted_proxies = sorted(filtered_proxies.items(), key=lambda x: x[1], reverse=True)

    result = []
    for proxy, score in sorted_proxies:
        if len(result) >= num:
            break
        actual_type = proxy_types.get(proxy, "http")
        china = china_support_dict.get(proxy, False)
        international = international_support_dict.get(proxy, False)
        transparent = transparent_proxies.get(proxy, False)
        result.append({
            'proxy': f"{actual_type}://{proxy}",
            'score': score,
            'china': china,
            'international': international,
            'transparent': transparent
        })

    return result

def extract_proxies_menu():
    """提取代理菜单（支持按类型、支持范围和透明代理筛选）"""
    try:
        count = int(input("请输入要提取的代理数量: ").strip())
        if count <= 0:
            print("数量必须大于0")
            return

        # 选择代理类型
        print("\n选择代理类型:")
        print("1. http/https")
        print("2. socks4")
        print("3. socks5")
        print("4. 全部类型")
        type_choice = input("请选择(1-4): ").strip()
        
        type_map = {
            "1": "http",
            "2": "socks4", 
            "3": "socks5",
            "4": "all"
        }
        
        proxy_type = type_map.get(type_choice, "all")
        
        # 选择支持范围
        print("\n选择支持范围:")
        print("1. 仅支持国内")
        print("2. 仅支持国际") 
        print("3. 支持国内外")
        print("4. 不限制支持范围")
        support_choice = input("请选择(1-4): ").strip()
        
        china_support = None
        international_support = None
        
        if support_choice == "1":
            china_support = True
            international_support = False
        elif support_choice == "2":
            china_support = False  
            international_support = True
        elif support_choice == "3":
            china_support = True
            international_support = True
        # 4 和其他情况不限制
        
        # 选择透明代理筛选
        print("\n选择透明代理筛选:")
        print("1. 仅提取透明代理")
        print("2. 仅提取非透明代理")
        print("3. 不限制")
        transparent_choice = input("请选择(1-3): ").strip()
        
        transparent_only = None
        if transparent_choice == "1":
            transparent_only = True
        elif transparent_choice == "2":
            transparent_only = False
        # 3 和其他情况不限制
        
        proxies = extract_proxies_by_type(count, proxy_type, china_support, international_support, transparent_only)
        if not proxies:
            print("代理池中没有符合条件的代理")
            return

        if len(proxies) < count:
            print(f"⚠️ 警告: 只有 {len(proxies)} 个符合条件代理，少于请求的 {count} 个")

        print(f"\n提取的代理列表({proxy_type}):")
        for i, proxy_info in enumerate(proxies, 1):
            support_desc = []
            if proxy_info['china']:
                support_desc.append("国内")
            if proxy_info['international']:
                support_desc.append("国际")
            support_str = "|".join(support_desc) if support_desc else "无"
            transparent_str = "⚠️透明" if proxy_info['transparent'] else "匿名"
            print(f"{i}. {proxy_info['proxy']} | 分数:{proxy_info['score']} | 支持:{support_str} | {transparent_str}")

        save_choice = input("是否保存到文件? (y/n): ").lower().strip()
        if save_choice == "y":
            filename = input("请输入文件名: ")
            with open(filename, "w", encoding="utf-8") as file:
                for proxy_info in proxies:
                    file.write(f"{proxy_info['proxy']}\n")
            print(f"已保存到 {filename}")
    except ValueError:
        print("请输入有效的数字")

def show_proxy_pool_status():
    """显示代理池状态（按类型、分数、支持范围和透明代理统计）"""
    proxies, proxy_types, china_support, international_support, transparent_proxies, _ = load_proxies_from_file(OUTPUT_FILE)
    total = len(proxies)
    
    if total == 0:
        print("代理池为空")
        return

    # 按类型分组
    type_groups = {}
    for proxy, score in proxies.items():
        proxy_type = proxy_types.get(proxy, "http")
        if proxy_type not in type_groups:
            type_groups[proxy_type] = []
        type_groups[proxy_type].append((proxy, score, china_support.get(proxy, False), international_support.get(proxy, False), transparent_proxies.get(proxy, False)))

    print(f"\n代理池状态 ({OUTPUT_FILE}):")
    print(f"总代理数量: {total}")
    
    # 支持范围统计
    china_only = sum(1 for proxy in proxies if china_support.get(proxy, False) and not international_support.get(proxy, False))
    intl_only = sum(1 for proxy in proxies if not china_support.get(proxy, False) and international_support.get(proxy, False))
    both_support = sum(1 for proxy in proxies if china_support.get(proxy, False) and international_support.get(proxy, False))
    no_support = total - china_only - intl_only - both_support
    
    # 透明代理统计
    transparent_count = sum(1 for proxy in proxies if transparent_proxies.get(proxy, False))
    anonymous_count = total - transparent_count
    
    print(f"\n支持范围统计:")
    print(f"  仅支持国内: {china_only}个")
    print(f"  仅支持国际: {intl_only}个") 
    print(f"  支持国内外: {both_support}个")
    print(f"  无支持(无效): {no_support}个")
    
    print(f"\n透明代理统计:")
    print(f"  ⚠️  透明代理: {transparent_count}个")
    print(f"  ✅ 匿名代理: {anonymous_count}个")
    
    # 按类型显示统计
    for proxy_type, proxy_list in type_groups.items():
        type_count = len(proxy_list)
        print(f"\n{proxy_type.upper()} 代理: {type_count}个")
        
        # 统计分数分布
        score_count = {}
        for _, score, _, _, _ in proxy_list:
            score_count[score] = score_count.get(score, 0) + 1
        
        # 按分数排序显示
        sorted_scores = sorted(score_count.items(), key=lambda x: x[0], reverse=True)
        for score, count in sorted_scores:
            print(f"  {score}分: {count}个")
        
    print('='*40)
    print(f'总计: {total} 个代理')

def load_from_csv_with_type():
    """从CSV文件加载并验证代理（支持类型选择，添加中断恢复）"""
    try:
        # 首先检查是否有中断记录
        remaining_proxies, proxy_type, original_count = load_interrupted_proxies(INTERRUPT_FILE_LOAD)
        if remaining_proxies:
            print(f"🔍 发现上次文件加载中断记录!")
            print(f"   剩余代理: {len(remaining_proxies)}/{original_count} 个")
            print(f"   验证类型: {proxy_type}")
            print("\n请选择:")
            print("  y: 继续上次验证")
            print("  n: 删除记录并重新选择文件")
            print("  其他: 返回上级菜单")
            
            choice = input("请选择 (y/n/其他): ").lower().strip()
            
            if choice == 'y':
                print("继续上次验证...")
                validate_new_proxies_with_interrupt(remaining_proxies, proxy_type, from_interrupt=True, source="load")
                return
            elif choice == 'n':
                delete_interrupt_file(INTERRUPT_FILE_LOAD)
                print("已删除中断记录，开始重新选择文件...")
            else:
                print("返回上级菜单")
                return

        filename = input('文件名(路径): ')
        if not os.path.exists(filename):
            print("文件不存在")
            return
            
        # 选择代理类型
        print("\n选择代理类型:")
        print("1. http/https")
        print("2. socks4")
        print("3. socks5")
        print("4. 自动检测")
        print("输入其他: 使用默认值http")
        type_choice = input("请选择(1-4): ").strip()
        
        type_map = {
            "1": "http",
            "2": "socks4",
            "3": "socks5",
            "4": "auto"
        }
        
        selected_type = type_map.get(type_choice, "http")
        print(f"使用类型: {selected_type}")
        
        # 选择是否检测透明代理
        print("\n是否检测透明代理?")
        print("1. 是（推荐）")
        print("2. 否（更快）")
        transparent_choice = input("请选择(1-2): ").strip()
        check_transparent = transparent_choice == "1"
        
        data = []
        with open(filename, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) >= 2:
                    # 支持 ip,port 格式
                    ip = row[0].strip()
                    port = row[1].strip()
                    if ip and port:
                        data.append(f"{ip}:{port}")
                elif len(row) == 1 and ':' in row[0]:
                    # 支持 ip:port 格式
                    data.append(row[0].strip())
        
        if not data:
            print("文件中没有找到有效的代理")
            return
            
        print(f"从文件加载了 {len(data)} 个代理")
        
        # 筛选去重
        new_proxies = filter_proxies(data)
        
        if new_proxies:
            if selected_type != "auto":
                # 使用指定类型验证
                validate_new_proxies_with_interrupt(new_proxies, selected_type, source="load", check_transparent=check_transparent)
            else:
                # 使用自动检测
                validate_new_proxies_with_interrupt(new_proxies, "auto", source="load", check_transparent=check_transparent)
        else:
            print("没有新代理需要验证")
            
    except Exception as e:
        print(f'出错了: {str(e)}')

def download_from_github():
    """从GitHub下载代理池并合并到本地"""
    print("\n开始从GitHub下载代理池...")
    
    github_url = "https://raw.githubusercontent.com/LiMingda-101212/Proxy-Pool/refs/heads/main/proxies.csv"
    
    try:
        # 下载GitHub上的代理池
        response = requests.get(github_url, timeout=30)
        if response.status_code != 200:
            print(f"❌ 下载失败，状态码: {response.status_code}")
            return
        
        # 解析GitHub代理池
        github_proxies = {}
        github_types = {}
        github_china = {}
        github_international = {}
        github_transparent = {}
        github_detected_ips = {}
        
        content = response.text.strip().split('\n')
        reader = csv.reader(content)
        
        for row in reader:
            if len(row) >= 7:
                # 新格式：类型,proxy:port,分数,China,International,Transparent,DetectedIP
                proxy_type = row[0].strip().lower()
                proxy = row[1].strip()
                try:
                    score = int(row[2])
                    china = row[3].strip().lower() == 'true'
                    international = row[4].strip().lower() == 'true'
                    transparent = row[5].strip().lower() == 'true'
                    detected_ip = row[6].strip() if len(row) > 6 else "unknown"
                    
                    github_proxies[proxy] = score
                    github_types[proxy] = proxy_type
                    github_china[proxy] = china
                    github_international[proxy] = international
                    github_transparent[proxy] = transparent
                    github_detected_ips[proxy] = detected_ip
                except Exception as e:
                    print(f"❌ 解析GitHub代理失败: {proxy} - {str(e)}")
                    continue
        
        print(f"✅ 从GitHub下载了 {len(github_proxies)} 个代理")
        
        # 加载本地代理池
        local_proxies, local_types, local_china, local_international, local_transparent, local_detected_ips = load_proxies_from_file(OUTPUT_FILE)
        
        # 合并代理池（以GitHub为主）
        merged_count = 0
        updated_count = 0
        new_count = 0
        
        for proxy, score in github_proxies.items():
            if proxy in local_proxies:
                # 代理已存在，比较分数
                if score > local_proxies[proxy]:
                    local_proxies[proxy] = score
                    local_types[proxy] = github_types[proxy]
                    local_china[proxy] = github_china[proxy]
                    local_international[proxy] = github_international[proxy]
                    local_transparent[proxy] = github_transparent[proxy]
                    local_detected_ips[proxy] = github_detected_ips[proxy]
                    updated_count += 1
                merged_count += 1
            else:
                # 新代理
                local_proxies[proxy] = score
                local_types[proxy] = github_types[proxy]
                local_china[proxy] = github_china[proxy]
                local_international[proxy] = github_international[proxy]
                local_transparent[proxy] = github_transparent[proxy]
                local_detected_ips[proxy] = github_detected_ips[proxy]
                new_count += 1
        
        # 保存合并后的代理池
        save_valid_proxies(local_proxies, local_types, local_china, local_international, local_transparent, local_detected_ips, OUTPUT_FILE)
        
        print(f"\n✅ 合并完成!")
        print(f"总代理数: {len(local_proxies)}")
        print(f"已存在代理: {merged_count}")
        print(f"更新代理: {updated_count}")
        print(f"新增代理: {new_count}")
        
    except Exception as e:
        print(f"❌ 下载失败: {str(e)}")

def crawl_proxies():
    """爬取免费代理（添加中断恢复检查）"""
    # 首先检查是否有中断记录
    remaining_proxies, proxy_type, original_count = load_interrupted_proxies(INTERRUPT_FILE)
    if remaining_proxies:
        print(f"🔍 发现上次中断记录!")
        print(f"   剩余代理: {len(remaining_proxies)}/{original_count} 个")
        print(f"   验证类型: {proxy_type}")
        print("\n请选择:")
        print("  y: 继续上次验证")
        print("  n: 删除记录并重新爬取")
        print("  其他: 返回上级菜单")
        
        choice = input("请选择 (y/n/其他): ").lower().strip()
        
        if choice == 'y':
            print("继续上次验证...")
            return remaining_proxies, proxy_type
        elif choice == 'n':
            delete_interrupt_file(INTERRUPT_FILE)
            print("已删除中断记录，开始重新爬取...")
        else:
            print("返回上级菜单")
            return None, None

    print("""已创建的可爬网站
    1 ：https://proxy5.net/cn/free-proxy/china
          备注:被封了,成功率 40%
    2 ：https://www.89ip.cn/
          备注:240个,成功率 10%
    3 ：https://cn.freevpnnode.com/
          备注:30个,成功率 3%
    4 ：https://www.kuaidaili.com/free/inha/ 
          备注:7600多页,成功率 5%
    5 ：http://www.ip3366.net/
          备注:100个,成功率 1%
    6 ：https://proxypool.scrape.center/random
          备注:随机的,成功率 40%
    7 ：https://proxy.scdn.io/text.php
          备注:12000多个,成功率 30%
    8 ：https://proxyhub.me/zh/cn-http-proxy-list.html
          备注:20个,成功率 0%
    9 : https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/http.txt
          备注:大约3000个,成功率 15%
    10: https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/socks5.txt
          备注:大约2000个,成功率 10%
    11: https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/https.txt
          备注:大约3000个,成功率 10%
    12: https://github.com/zloi-user/hideip.me/raw/refs/heads/master/http.txt
          备注:大约1000个,成功率 20%
    13: https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt
          备注:大约1000个,成功率 0%
    14: https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks4.txt
          备注:大约100个,成功率 30%
    15: https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt
          备注:大约50个,成功率 30% 
    16: https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt
          备注:大约50000个,成功率 0.001%
    17: https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt
          备注:大约50000个,成功率 0.001%
    18: https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt
          备注:大约4000个,成功率 0.01%
          
    输入其他：退出
    """)
    scraper_choice = input("选择：").strip()
    all_proxies = []  # 存储所有爬取的代理
    by_type = ''  # 通过指定类型验证,默认为否

    if scraper_choice == "1":
        print('开始爬取:https://proxy5.net/cn/free-proxy/china')
        error_count = 0
        '''
        <tr>.*?<td><strong>(?P<ip>.*?)</strong></td>.*?<td>(?P<port>.*?)</td>.*?</tr>
        '''
        proxy_list = ProxyScraper('https://proxy5.net/cn/free-proxy/china',
                        "<tr>.*?<td><strong>(?P<ip>.*?)</strong></td>.*?<td>(?P<port>.*?)</td>.*?</tr>",
                        ["ip", "port"]).scrape_proxies()
        
        if isinstance(proxy_list, list):
            all_proxies.extend(proxy_list)
        else:
            error_count += 1
        print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')

    elif scraper_choice == "2":
        print('开始爬取:https://www.89ip.cn/')
        error_count = 0
        total_pages = 6
        for page in range(1, total_pages+1):
            if page == 1:
                url = 'https://www.89ip.cn/'
            else:
                url = f'https://www.89ip.cn/index_{page}.html'

            proxy_list = ProxyScraper(url,"<tr>.*?<td>(?P<ip>.*?)</td>.*?<td>(?P<port>.*?)</td>.*?</tr>",
                            ["ip", "port"]).scrape_proxies()
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1

            time.sleep(1)

            # 计算进度百分比
            percent = page * 100 // total_pages
            # 计算进度条长度
            completed = page * 50 // total_pages
            remaining = 50 - completed
            # 处理百分比显示的对齐
            if percent < 10:
                padding = "  "
            elif percent < 100:
                padding = " "
            else:
                padding = ""
            # 更新进度条
            print(f"\r{percent}%{padding}|{'█' * completed}{'-' * remaining}| {page}/{total_pages}  错误数:{error_count}", end="")
            sys.stdout.flush()
        print('\n')
        
    elif scraper_choice == "3":
        print('\n开始爬取:https://cn.freevpnnode.com/')
        error_count = 0
        proxy_list = ProxyScraper("https://cn.freevpnnode.com/",
                        '<tr>.*?<td>(?P<ip>.*?)</td>.*?<td>(?P<port>.*?)</td>.*?<td><span>.*?</span> <img src=".*?" width="20" height="20" .*? class="js_openeyes"></td>.*?</td>',
                        ["ip", "port"]).scrape_proxies()
        if isinstance(proxy_list, list):
            all_proxies.extend(proxy_list)
        else:
            error_count += 1
        print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')

    elif scraper_choice == "4":
        error_count = 0
        try:
            print('信息:共约7000页,建议一次爬取数量不大于500页,防止被封')
            start_page = int(input('爬取起始页（整数）：').strip())
            end_page = int(input("爬取结束页（整数）:").strip())
            if end_page < 1 or start_page < 1 or end_page > 7000 or start_page > 7000 or start_page > end_page:
                print("不能小于1或大于7000,起始页不能大于结束页")
                return

            print('开始爬取:https://www.kuaidaili.com/free/inha/')
            
            for page in range(start_page, end_page + 1):

                proxy_list = ProxyScraper(f"https://www.kuaidaili.com/free/inha/{page}/",
                                '{"ip": "(?P<ip>.*?)", "last_check_time": ".*?", "port": "(?P<port>.*?)", "speed": .*?, "location": ".*?"}',
                                ["ip", "port"]).scrape_proxies()
                if isinstance(proxy_list, list):
                    all_proxies.extend(proxy_list)
                else:
                    error_count += 1

                time.sleep(2)

                # 计算进度百分比
                current_page = page - start_page + 1
                total_pages = end_page - start_page + 1
                percent = current_page * 100 // total_pages
                # 计算进度条长度
                completed = current_page * 50 // total_pages
                remaining = 50 - completed
                # 处理百分比显示的对齐
                if percent < 10:
                    padding = "  "
                elif percent < 100:
                    padding = " "
                else:
                    padding = ""
                # 更新进度条
                print(f"\r{percent}%{padding}|{'█' * completed}{'-' * remaining}| {current_page}/{total_pages}  错误数:{error_count}", end="")
                sys.stdout.flush()
            print('\n')
        except:
            print("输入错误，请输入整数")

    elif scraper_choice == "5":

        print('\n开始爬取:http://www.ip3366.net/?stype=1')
        total_pages = 7
        error_count = 0
        for page in range(1, total_pages + 1):
            proxy_list = ProxyScraper(f'http://www.ip3366.net/?stype=1&page={page}',
                            '<tr>.*?<td>(?P<ip>.*?)</td>.*?<td>(?P<port>.*?)</td>.*?</tr>', ['ip', 'port']).scrape_proxies()
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1

            time.sleep(1)

            # 计算进度百分比
            percent = page * 100 // total_pages
            # 计算进度条长度
            completed = page * 50 // total_pages
            remaining = 50 - completed
            # 处理百分比显示的对齐
            if percent < 10:
                padding = "  "
            elif percent < 100:
                padding = " "
            else:
                padding = ""
            # 更新进度条
            print(f"\r{percent}%{padding}|{'█' * completed}{'-' * remaining}| {page}/{total_pages}  错误数:{error_count}", end="")
            sys.stdout.flush()
        print('\n')

    elif scraper_choice == "6":
        try:
            by_type = 'http'   # 默认用http
            count = int(input("爬取个数(整数)：").strip())
            if count < 1:
                print("数量必须大于0")
                return None,None

            print(f"\n开始爬取 {count} 个代理...")
        
            try:
                # 适合用协程
                import aiohttp
                import asyncio
                
                async def fetch_proxy(session, url, semaphore):
                    async with semaphore:
                        try:
                            async with session.get(url) as response:
                                if response.status == 200:
                                    proxy = await response.text()
                                    print(proxy)
                                    return proxy.strip()
                        except:
                            return None
                
                async def fetch_proxies_main():
                    semaphore = asyncio.Semaphore(20)   # 最大并发
                    timeout = aiohttp.ClientTimeout(total=50)   # 超时(给服务器足够响应时间)
                    
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        tasks = []
                        for _ in range(count):
                            url = 'https://proxypool.scrape.center/random'
                            task = fetch_proxy(session, url, semaphore)
                            tasks.append(task)
                        
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        return [r for r in results if r and isinstance(r, str) and ':' in r]
                
                proxies = asyncio.run(fetch_proxies_main())
                if proxies:
                    all_proxies.extend(proxies)
                    
            except ImportError:
                print("aiohttp 未安装，使用同步请求...")
                # 同步备选方案
                for _ in range(count):
                    try:
                        proxy = requests.get('https://proxypool.scrape.center/random', timeout=10).text.strip()
                        if proxy and ':' in proxy:
                            all_proxies.append(proxy)
                    except:
                        continue

            print(f"\n爬取完成！")
        except ValueError:
            print("输入错误")
            return None, None

    elif scraper_choice == '7':
        print("\n开始爬取:https://proxy.scdn.io/text.php")
        error_count = 0
        url = 'https://proxy.scdn.io/text.php'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
            'Referer':'https://proxy.scdn.io/'
        }
        try:
            response = requests.get(url,headers=headers)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')
    
    elif scraper_choice == '8':
        print('\n开始爬取:https://proxyhub.me/zh/cn-http-proxy-list.html')
        error_count = 0
        proxy_list = ProxyScraper("https://proxyhub.me/zh/cn-http-proxy-list.html",
                        r'<tr>\s*<td>(?P<ip>\d+\.\d+\.\d+\.\d+)</td>\s*<td>(?P<port>\d+)</td>',
                        ["ip", "port"]).scrape_proxies()
        if isinstance(proxy_list, list):
            all_proxies.extend(proxy_list)
        else:
            error_count += 1
        print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')

    # https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/http.txt -> https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt
    # https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/socks5.txt -> https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt
    # https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/https.txt -> https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/https.txt
    elif scraper_choice == '9':
        by_type = 'http'   # 默认用http
        print('\n开始爬取:https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '10':
        by_type = 'socks5'   # 默认用socks5
        print('\n开始爬取:https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt'
        try:
            response = requests.get(url,headers=HEADERS)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '11':
        by_type = 'http'   # 默认用http
        print('\n开始爬取:https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/https.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/https.txt'
        try:
            response = requests.get(url,headers=HEADERS)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/http.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/http.txt
    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/https.txt
    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks4.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks4.txt
    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks5.txt
    elif scraper_choice == '12':
        by_type = 'http'   # 默认用http
        print('\n开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/http.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/http.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = re.sub(r':\D.*?\n','\n',response.text).split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '13':
        by_type = 'http'   # 默认用http
        print('\n开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/https.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/https.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = re.sub(r':\D.*?\n','\n',response.text).split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '14':
        by_type = 'socks4'
        print('\n开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks4.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks4.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = re.sub(r':\D.*?\n','\n',response.text).split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '15':
        by_type = 'socks5'
        print('\n开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks5.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks5.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = re.sub(r':\D.*?\n','\n',response.text).split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    # https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt
    # https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt
    # https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt
    elif scraper_choice == '16':
        by_type = 'http'
        print('\n开始爬取:https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')
    
    elif scraper_choice == '17':
        by_type = 'socks4'
        print('\n开始爬取:https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')
    
    elif scraper_choice == '18':
        by_type = 'socks5'
        print('\n开始爬取:https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt'

        try:
            response = requests.get(url,headers=HEADERS)
            result = response.text.split("\n")
            proxy_list = []
            for proxy in result:
                if len(result) == 0:
                    print('没有代理可以爬取')
                else:
                    proxy_list.append(proxy.strip())
            if isinstance(proxy_list, list):
                all_proxies.extend(proxy_list)
            else:
                error_count += 1
            print(f'100%|██████████████████████████████████████████████████| 1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')


    # https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/refs/heads/master/http.txt -> 质量很差,暂时不添加

    # https://github.com/FifzzSENZE/Master-Proxy.git -> 质量一般,暂时不添加
    # https://github.com/dpangestuw/Free-Proxy.git -> 质量一般,暂时不添加
    # https://github.com/watchttvv/free-proxy-list.git -> 可以,但比较少
    # https://github.com/trio666/proxy-checker.git
    
    return filter_proxies(all_proxies), by_type

if __name__ == '__main__':
    # 创建中断目录
    create_interrupt_dir()

    while True:
        print(f"""功能：
        1: 加载并验证新代理 (成功后添加到代理池)
        2: 检验并更新已有代理
        3: 提取代理(可指定数量,类型,支持范围,透明代理)
        4: 查看代理池状态
        5: 同步代理池（GitHub）


        输入其他: 退出
        """)
        choice = input("选择：").strip()

        if choice == "1":
            print('''来自:
                  1: 来自爬虫爬取
                  2: 来自本地文件(proxy,port)

                  输入其他: 返回上级菜单
            ''')
            from_choice = input('选择:').strip()

            if from_choice == '1':
                new_proxies, by_type = crawl_proxies()
                if new_proxies:   # 如果有新代理
                    # 检查是否是从中断恢复的
                    remaining_proxies, interrupt_type, _ = load_interrupted_proxies()
                    from_interrupt = remaining_proxies is not None and remaining_proxies == new_proxies
                    
                    # 询问是否检测透明代理
                    print("\n是否检测透明代理?")
                    print("1. 是（推荐，识别会泄露真实IP的代理）")
                    print("2. 否（更快）")
                    transparent_choice = input("请选择(1-2): ").strip()
                    check_transparent = transparent_choice == "1"
                    
                    if by_type:   # 如果指定类型
                        validate_new_proxies_with_interrupt(new_proxies, by_type, from_interrupt, check_transparent=check_transparent)
                    else:   # 没有指定类型
                        validate_new_proxies_with_interrupt(new_proxies, "auto", from_interrupt, check_transparent=check_transparent)

            elif from_choice == '2':
                load_from_csv_with_type()

            else:
                print('返回上级菜单')
                continue

        elif choice == "2":
            # 询问是否检测透明代理
            print("\n是否检测透明代理?")
            print("1. 是（推荐，识别会泄露真实IP的代理）")
            print("2. 否（更快）")
            transparent_choice = input("请选择(1-2): ").strip()
            check_transparent = transparent_choice == "1"
            
            validate_existing_proxies_with_interrupt(check_transparent)

        elif choice == "3":
            extract_proxies_menu()

        elif choice == "4":
            show_proxy_pool_status()
        
        elif choice == "5":
            download_from_github()

        else:
            print('退出')
            break

```
