
import re
import requests
import concurrent.futures
import time
import os
import csv

# ============配置区
OUTPUT_FILE = "proxies.csv"  # 输出有效代理文件
TEST_URL = "http://httpbin.org/ip"  # 测试URL
TIMEOUT = 6  # 超时时间(秒)
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
            response = requests.get(url=self.url, headers=self.headers, timeout=TIMEOUT)
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

def check_proxy(proxy, test_url="http://httpbin.org/ip", timeout=TIMEOUT, 
                retries=1, proxy_type="auto"):
    """
    检查单个代理IP的可用性
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
                    origin_ip = response.json().get('origin', '')
                    proxy_ip = proxy.split(':')[0]
                    if proxy_ip in origin_ip:
                        detected_type = current_protocol
                        return proxy, True, response_time, detected_type
                    detected_type = current_protocol
                    return proxy, True, response_time, detected_type
                    
            except Exception:
                if attempt < retries - 1:
                    time.sleep(0.5)
                    continue
                break
                
    if proxy_type != "auto":
        detected_type = proxy_type
    
    return proxy, False, None, detected_type

def check_proxies_batch(proxies, proxy_types, test_url="http://httpbin.org/ip", 
                       timeout=TIMEOUT, max_workers=MAX_WORKERS, check_type="new"):
    """
    批量检查代理IP列表
    """
    updated_proxies = {}
    updated_types = {}

    retries = 2 if check_type == "new" else 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {}
        for proxy in proxies:
            if check_type == "existing" and proxy in proxy_types:
                proxy_type = proxy_types[proxy]
            else:
                proxy_type = proxy_types.get(proxy, "auto")
                
            future = executor.submit(
                check_proxy,
                proxy,
                test_url,
                timeout,
                retries,
                proxy_type
            )
            future_to_proxy[future] = proxy

        for future in concurrent.futures.as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            try:
                proxy_addr, is_valid, response_time, detected_type = future.result()

                if is_valid and response_time is not None and response_time <= timeout:
                    print(f"✅ 有效代理({detected_type}): {proxy} | 响应时间: {response_time:.2f}s")
                    if check_type == "new":
                        updated_proxies[proxy] = 98
                    else:
                        current_score = proxies.get(proxy, 0)
                        updated_proxies[proxy] = min(current_score + 1, MAX_SCORE)
                    updated_types[proxy] = detected_type
                    
                elif response_time is not None:
                    print(f"❎ 超时代理: {proxy} | 响应时间: {response_time:.2f}s")
                    if check_type == "existing" and proxy in proxies:
                        updated_proxies[proxy] = proxies[proxy]
                    else:
                        updated_proxies[proxy] = 80
                    updated_types[proxy] = proxy_types.get(proxy, detected_type)

                else:
                    print(f"❌ 无效代理: {proxy}")
                    if check_type == "existing" and proxy in proxies:
                        updated_proxies[proxy] = max(0, proxies[proxy] - 1)
                        updated_types[proxy] = proxy_types.get(proxy, "http")
                    else:
                        updated_proxies[proxy] = 0
                        updated_types[proxy] = proxy_types.get(proxy, "http")
                        
            except Exception as e:
                print(f"❌ 错误代理: {proxy} - {str(e)}")
                if check_type == "existing" and proxy in proxies:
                    updated_proxies[proxy] = max(0, proxies[proxy] - 1)
                    updated_types[proxy] = proxy_types.get(proxy, "http")
                else:
                    updated_proxies[proxy] = 0
                    updated_types[proxy] = proxy_types.get(proxy, "http")
                    
    return updated_proxies, updated_types

def load_proxies_from_file(file_path):
    """从CSV文件加载代理列表、类型和分数"""
    proxies = {}
    proxy_types = {}
    
    if not os.path.exists(file_path):
        return proxies, proxy_types

    with open(file_path, 'r', encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) >= 3:
                proxy_type = row[0].strip().lower()
                proxy = row[1].strip()
                try:
                    score = int(row[2])
                    proxies[proxy] = score
                    proxy_types[proxy] = proxy_type
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
            elif len(row) >= 2:
                proxy = row[0].strip()
                try:
                    score = int(row[1])
                    proxies[proxy] = score
                    proxy_types[proxy] = "http"
                except:
                    proxies[proxy] = 70
                    proxy_types[proxy] = "http"
    
    return proxies, proxy_types

def save_valid_proxies(proxies, proxy_types, file_path):
    """保存有效代理到CSV文件"""
    # os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    with open(file_path, 'w', encoding="utf-8", newline='') as file:
        writer = csv.writer(file)
        for proxy, score in proxies.items():
            if len(proxy) > 6 and score > 0:
                proxy_type = proxy_types.get(proxy, "http")
                writer.writerow([proxy_type, proxy, score])

def update_proxy_scores(file_path):
    """更新代理分数文件，移除0分代理"""
    proxies, proxy_types = load_proxies_from_file(file_path)
    valid_proxies = {k: v for k, v in proxies.items() if v > 0}
    valid_types = {k: v for k, v in proxy_types.items() if k in valid_proxies}
    save_valid_proxies(valid_proxies, valid_types, file_path)
    return len(proxies) - len(valid_proxies)

def filter_proxies(all_proxies):
    """从新获取代理中去掉无效的,重复的"""
    existing_proxies = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE,'r') as file:
            csv_reader  = csv.reader(file)
            for row in csv_reader:
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
    """验证新代理"""
    if not new_proxies:
        print("没有代理需要验证")
        return

    original_count = len(new_proxies)
    print(f"共加载 {original_count} 个新代理，使用{proxy_type}类型开始测试...")
    
    new_proxies_dict = {proxy: 0 for proxy in new_proxies}
    new_types_dict = {proxy: proxy_type for proxy in new_proxies}
    
    updated_proxies, updated_types = check_proxies_batch(
        new_proxies_dict, new_types_dict, TEST_URL, TIMEOUT, 
        MAX_WORKERS, check_type="new"
    )
    
    # 合并到现有代理池
    existing_proxies, existing_types = load_proxies_from_file(OUTPUT_FILE)
    for proxy, score in updated_proxies.items():
        if proxy not in existing_proxies or existing_proxies[proxy] < score:
            existing_proxies[proxy] = score
            existing_types[proxy] = updated_types[proxy]

    save_valid_proxies(existing_proxies, existing_types, OUTPUT_FILE)
    
    # 统计结果
    success_count = sum(1 for score in updated_proxies.values() if score == 98)
    timeout_count = sum(1 for score in updated_proxies.values() if score == 80)
    
    print(f"\n✅ 验证完成!")
    print(f"成功: {success_count}/{original_count}")
    print(f"超时: {timeout_count}/{original_count}")
    print(f"代理池已更新至: {OUTPUT_FILE}")

def validate_existing_proxies():
    """验证已有代理池中的代理"""
    print(f"开始验证已有代理池，文件：{OUTPUT_FILE}...")
    
    # 加载代理池
    all_proxies, proxy_types = load_proxies_from_file(OUTPUT_FILE)
    
    if not all_proxies:
        print("没有代理需要验证")
        return

    print(f"共加载 {len(all_proxies)} 个代理，开始测试...")
    
    updated_proxies, updated_types = check_proxies_batch(
        all_proxies, proxy_types, TEST_URL, TIMEOUT, MAX_WORKERS, "existing"
    )
    
    # 更新所有代理分数
    for proxy, score in updated_proxies.items():
        all_proxies[proxy] = score
    
    # 保存更新后的代理池
    save_valid_proxies(all_proxies, proxy_types, OUTPUT_FILE)
    
    # 清理0分代理
    removed_count = update_proxy_scores(OUTPUT_FILE)
    
    # 最终统计
    final_proxies, _ = load_proxies_from_file(OUTPUT_FILE)
    final_count = len(final_proxies)

    print(f"\n验证完成! 剩余有效代理: {final_count}/{len(all_proxies)}")
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

    # https://github.com/themiralay/Proxy-List-World.git
    # https://github.com/FifzzSENZE/Master-Proxy.git
    # https://github.com/dpangestuw/Free-Proxy.git
    # https://github.com/watchttvv/free-proxy-list.git
    # https://github.com/trio666/proxy-checker.git
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
