import re
import requests
import concurrent.futures
import time
import os
import csv

# ============配置区
OUTPUT_FILE = "proxies.csv"  # 输出有效代理文件
TEST_URL_CN = "http://www.baidu.com"  # 国内测试URL
TEST_URL_INTL = "http://www.google.com"  # 国际测试URL
TIMEOUT_CN = 6  # 国内测试超时时间(秒)
TIMEOUT_INTL = 10  # 国际测试超时时间(秒)
MAX_WORKERS = 50  # 最大并发数
MAX_SCORE = 100  # 最大积分

class ProxyScraper:
    """代理爬取器"""
    def __init__(self, url: str, regex_pattern: str, capture_groups: list):
        self.url = url
        self.headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0'
        }
        self.encoding = "utf-8"
        self.regex_pattern = regex_pattern
        self.capture_groups = capture_groups

    def scrape_proxies(self):
        extracted_data = []
        try:
            response = requests.get(url=self.url, headers=self.headers, timeout=TIMEOUT_CN)
            if response.status_code == 200:
                response.encoding = self.encoding
                regex = re.compile(self.regex_pattern, re.S)
                matches = regex.finditer(response.text)
                for match in matches:
                    for group_name in self.capture_groups:
                        extracted_data.append(f"{match.group(group_name)}")
                proxy_list = [f"{extracted_data[i].strip()}:{extracted_data[i + 1].strip()}" 
                            for i in range(0, len(extracted_data), 2)]
                response.close()
                return proxy_list
            else:
                print(f"爬取失败，状态码: {response.status_code}")
                return []
        except Exception as e:
            print(f"爬取失败，错误: {str(e)}")
            return []

def check_proxy_single(proxy, test_url, timeout=TIMEOUT_CN, 
                      retries=1, proxy_type="auto"):
    """
    检查单个代理IP对单个URL的可用性
    """
    if proxy_type == "auto":
        protocols_to_try = ["http", "socks5", "socks4"]
    else:
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
                    break

                if response.status_code == 200:
                    detected_type = current_protocol
                    return True, response_time, detected_type
                    
            except Exception:
                if attempt < retries - 1:
                    time.sleep(0.5)
                    continue
                break
                
    if proxy_type != "auto":
        detected_type = proxy_type
    
    return False, None, detected_type

def check_proxy_dual(proxy, proxy_type="auto"):
    """
    双重验证代理：同时验证百度(国内)和Google(国际)
    
    :return: (是否通过国内, 是否通过国际, 最终检测类型)
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
    
    return cn_success, intl_success, final_type

def check_proxies_batch(proxies, proxy_types, max_workers=MAX_WORKERS, check_type="new"):
    """
    批量检查代理IP列表（双重验证）
    """
    updated_proxies = {}
    updated_types = {}
    updated_china = {}
    updated_international = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {}
        for proxy in proxies:
            # 对于已有代理，使用文件中记录的类型；对于新代理，使用自动检测
            if check_type == "existing" and proxy in proxy_types:
                proxy_type = proxy_types[proxy]
            else:
                proxy_type = proxy_types.get(proxy, "auto")  # 从传入的类型字典获取
                
            future = executor.submit(check_proxy_dual, proxy, proxy_type)
            future_to_proxy[future] = proxy

        for future in concurrent.futures.as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            try:
                cn_success, intl_success, detected_type = future.result()

                # 计算分数和更新逻辑
                current_score = proxies.get(proxy, 0)
                
                if check_type == "new":
                    # 新代理：只要通过任一测试就98分
                    if cn_success or intl_success:
                        updated_proxies[proxy] = 98
                        print(f"✅ 代理有效({detected_type}): {proxy} | 国内: {'✓' if cn_success else '✗'} 国际: {'✓' if intl_success else '✗'}")
                    else:
                        updated_proxies[proxy] = 0
                        print(f"❌ 代理无效: {proxy}")
                else:
                    # 已有代理：根据测试结果调整分数
                    if cn_success and intl_success:
                        # 两次都通过，加2分
                        updated_proxies[proxy] = min(current_score + 2, MAX_SCORE)
                        print(f"✅ 代理有效({detected_type}): {proxy} | 国内: ✓ 国际: ✓ | 分数: {current_score} -> {updated_proxies[proxy]}")
                    elif cn_success or intl_success:
                        # 只通过一个，加1分
                        updated_proxies[proxy] = min(current_score + 1, MAX_SCORE)
                        status = "国内: ✓ 国际: ✗" if cn_success else "国内: ✗ 国际: ✓"
                        print(f"🟡 代理部分有效({detected_type}): {proxy} | {status} | 分数: {current_score} -> {updated_proxies[proxy]}")
                    else:
                        # 两个都不通过，减1分
                        updated_proxies[proxy] = max(0, current_score - 1)
                        print(f"❌ 代理无效({detected_type}): {proxy} | 国内: ✗ 国际: ✗ | 分数: {current_score} -> {updated_proxies[proxy]}")
                
                # 记录类型和支持范围
                updated_types[proxy] = detected_type
                updated_china[proxy] = cn_success
                updated_international[proxy] = intl_success
                        
            except Exception as e:
                print(f"❌ 错误代理: {proxy} - {str(e)}")
                
                if check_type == "existing" and proxy in proxies:
                    updated_proxies[proxy] = max(0, proxies[proxy] - 1)
                else:
                    updated_proxies[proxy] = 0
                
                updated_types[proxy] = proxy_types.get(proxy, "http")
                updated_china[proxy] = False
                updated_international[proxy] = False
                    
    return updated_proxies, updated_types, updated_china, updated_international

def load_proxies_from_file(file_path):
    """从CSV文件加载代理列表、类型、分数和支持范围"""
    proxies = {}
    proxy_types = {}
    china_support = {}
    international_support = {}
    
    if not os.path.exists(file_path):
        return proxies, proxy_types, china_support, international_support

    with open(file_path, 'r', encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) >= 5:
                # 新格式：类型,proxy:port,分数,China,International
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
                except:
                    # 如果解析失败，使用默认值
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
            elif len(row) >= 3:
                # 旧格式兼容：类型,proxy:port,分数（默认不支持任何范围）
                proxy_type = row[0].strip().lower()
                proxy = row[1].strip()
                try:
                    score = int(row[2])
                    proxies[proxy] = score
                    proxy_types[proxy] = proxy_type
                    china_support[proxy] = False
                    international_support[proxy] = False
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
            elif len(row) >= 2:
                # 更旧格式兼容：proxy:port,分数（默认HTTP类型）
                proxy = row[0].strip()
                try:
                    score = int(row[1])
                    proxies[proxy] = score
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
                    china_support[proxy] = False
                    international_support[proxy] = False
    
    return proxies, proxy_types, china_support, international_support

def save_valid_proxies(proxies, proxy_types, china_support, international_support, file_path):
    """保存有效代理到CSV文件（带类型、分数和支持范围）"""
    with open(file_path, 'w', encoding="utf-8", newline='') as file:
        writer = csv.writer(file)
        for proxy, score in proxies.items():
            if len(proxy) > 6 and score > 0:  # 基本验证
                proxy_type = proxy_types.get(proxy, "http")
                china = china_support.get(proxy, False)
                international = international_support.get(proxy, False)
                writer.writerow([proxy_type, proxy, score, china, international])

def update_proxy_scores(file_path):
    """更新代理分数文件，移除0分代理"""
    proxies, proxy_types, china_support, international_support = load_proxies_from_file(file_path)
    valid_proxies = {k: v for k, v in proxies.items() if v > 0}
    valid_types = {k: v for k, v in proxy_types.items() if k in valid_proxies}
    valid_china = {k: v for k, v in china_support.items() if k in valid_proxies}
    valid_international = {k: v for k, v in international_support.items() if k in valid_proxies}
    save_valid_proxies(valid_proxies, valid_types, valid_china, valid_international, file_path)
    return len(proxies) - len(valid_proxies)

def filter_proxies(all_proxies):
    """从新获取代理中去掉无效的,重复的"""
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
                duplicate_count += 1
            elif (':' in proxy) and (proxy not in new_proxies):
                new_proxies.append(proxy)
            else:
                invalid_count += 1
        except:
            invalid_count += 1

    print(f'新代理:{len(new_proxies)},已有(重复):{duplicate_count},无效:{invalid_count}')
    return new_proxies

def validate_new_proxies(new_proxies, proxy_type="auto"):
    """验证新代理（支持国内外）"""
    if not new_proxies:
        print("没有代理需要验证")
        return

    original_count = len(new_proxies)
    print(f"共加载 {original_count} 个新代理，使用{proxy_type}类型开始双重测试...")
    
    new_proxies_dict = {proxy: 0 for proxy in new_proxies}
    new_types_dict = {proxy: proxy_type for proxy in new_proxies}
    
    updated_proxies, updated_types, updated_china, updated_international = check_proxies_batch(
        new_proxies_dict, new_types_dict, MAX_WORKERS, check_type="new"
    )
    
    # 合并到现有代理池
    existing_proxies, existing_types, existing_china, existing_international = load_proxies_from_file(OUTPUT_FILE)
    for proxy, score in updated_proxies.items():
        if proxy not in existing_proxies or existing_proxies[proxy] < score:
            existing_proxies[proxy] = score
            existing_types[proxy] = updated_types[proxy]
            existing_china[proxy] = updated_china[proxy]
            existing_international[proxy] = updated_international[proxy]

    save_valid_proxies(existing_proxies, existing_types, existing_china, existing_international, OUTPUT_FILE)
    
    # 统计结果
    success_count = sum(1 for score in updated_proxies.values() if score == 98)
    china_only = sum(1 for proxy in updated_proxies if updated_china[proxy] and not updated_international[proxy])
    intl_only = sum(1 for proxy in updated_proxies if not updated_china[proxy] and updated_international[proxy])
    both_support = sum(1 for proxy in updated_proxies if updated_china[proxy] and updated_international[proxy])
    
    print(f"\n✅ 验证完成!")
    print(f"成功代理: {success_count}/{original_count}")
    print(f"仅支持国内: {china_only} | 仅支持国际: {intl_only} | 双支持: {both_support}")
    print(f"代理池已更新至: {OUTPUT_FILE}")

def validate_existing_proxies():
    """验证已有代理池中的代理（支持国内外）"""
    print(f"开始验证已有代理池，文件：{OUTPUT_FILE}...")
    
    # 加载代理池（不加载旧的支持范围，以新验证结果为准）
    all_proxies, proxy_types, _, _ = load_proxies_from_file(OUTPUT_FILE)
    
    if not all_proxies:
        print("没有代理需要验证")
        return

    print(f"共加载 {len(all_proxies)} 个代理，开始双重测试...")
    
    # 从代理池中获取当前分数和类型（不获取旧的支持范围）
    updated_proxies, updated_types, updated_china, updated_international = check_proxies_batch(
        all_proxies, proxy_types, MAX_WORKERS, "existing"
    )
    
    # 更新所有代理分数和支持范围
    for proxy, score in updated_proxies.items():
        all_proxies[proxy] = score
        proxy_types[proxy] = updated_types[proxy]
    
    # 保存更新后的代理池
    save_valid_proxies(all_proxies, proxy_types, updated_china, updated_international, OUTPUT_FILE)
    
    # 清理0分代理
    removed_count = update_proxy_scores(OUTPUT_FILE)
    
    # 最终统计
    final_proxies, _, final_china, final_international = load_proxies_from_file(OUTPUT_FILE)
    final_count = len(final_proxies)
    
    china_only = sum(1 for proxy in final_proxies if final_china[proxy] and not final_international[proxy])
    intl_only = sum(1 for proxy in final_proxies if not final_china[proxy] and final_international[proxy])
    both_support = sum(1 for proxy in final_proxies if final_china[proxy] and final_international[proxy])

    print(f"\n验证完成! 剩余有效代理: {final_count}/{len(all_proxies)}")
    print(f"仅支持国内: {china_only} | 仅支持国际: {intl_only} | 双支持: {both_support}")
    print(f"已移除 {removed_count} 个无效代理")

def main(scraper_choice):
    all_proxies = []  # 存储所有爬取的代理
    by_type = ''  # 通过指定类型验证,默认为否

    if scraper_choice == "1":
        try:
            by_type = 'http'   # 默认用http
            count = 1000

            print(f"开始爬取 {count} 个代理...")
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
                        proxy = requests.get('https://proxypool.scrape.center/random', timeout=30).text.strip()
                        if proxy and ':' in proxy:
                            all_proxies.append(proxy)
                    except:
                        continue

            print(f"爬取完成！")
        except ValueError:
            print("错误")
            return None, None
    
    # https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/http.txt -> https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt
    # https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/socks5.txt -> https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt
    # https://github.com/databay-labs/free-proxy-list/raw/refs/heads/master/https.txt -> https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/https.txt
    elif scraper_choice == '2':
        by_type = 'http'   # 默认用http
        print('开始爬取:https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '3':
        by_type = 'socks5'   # 默认用socks5
        print('开始爬取:https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '4':
        by_type = 'http'   # 默认用http
        print('开始爬取:https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/https.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/https.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/http.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/http.txt
    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/https.txt
    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks4.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks4.txt
    # https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt -> https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks5.txt
    elif scraper_choice == '5':
        by_type = 'http'   # 默认用http
        print('开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/http.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/http.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }
        try:
            response = requests.get(url,headers=headers)
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '6':
        by_type = 'http'   # 默认用http
        print('开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/https.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/https.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }
        try:
            response = requests.get(url,headers=headers)
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '7':
        by_type = 'socks4'
        print('开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks4.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks4.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }
        try:
            response = requests.get(url,headers=headers)
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    elif scraper_choice == '8':
        by_type = 'socks5'
        print('开始爬取:https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks5.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/zloi-user/hideip.me/refs/heads/master/socks5.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }
        try:
            response = requests.get(url,headers=headers)
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    # https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt
      
    elif scraper_choice == '9':
        by_type = 'socks5'
        print('开始爬取:https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt')
        error_count = 0
        url = 'https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
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
            print(f'1/1  错误数:{error_count}')
        except Exception as e:
            print(f'爬取失败: {str(e)}')

    return filter_proxies(all_proxies) , by_type

if __name__ == '__main__':
    # 主流程：爬取 -> 验证新代理 -> 验证已有代理
    print("=== 开始代理爬取和验证流程 ===")
    
    for i in range(1,9+1):
        # 1. 爬取新代理
        new_proxies,by_type = main(scraper_choice=str(i))

        # 2. 验证新代理
        if new_proxies:
            if by_type:
                validate_new_proxies(new_proxies,by_type)
            else:
                validate_new_proxies(new_proxies, "auto")

    # 3. 全爬完后验证已有代理
    validate_existing_proxies()
    
    print("=== 流程完成 ===")
