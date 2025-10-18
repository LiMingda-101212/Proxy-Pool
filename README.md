## 一个github actions自动代理爬取仓库

每天北京时间10-12点运行一次

### actions当前状态

![Proxy Pool Update](https://github.com/LiMingda-101212/Proxy-Pool/actions/workflows/proxy-crawler.yml/badge.svg)

### 介绍

1. 代理池文件(csv)介绍：

```
类型,代理,分数,是否支持中国,是否支持国际,是否为透明代理,识别到的ip
Type,Proxy:Port,Score,,China,International,Transparent,DetectedIP
```

2. 提取函数:

```python

import os
import csv

OUTPUT_FILE = "../Proxy-Pool/proxies.csv"

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

    return proxies, proxy_types, china_support, international_support, transparent_proxies, detected_ips

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
            support_str = "|".join(support_desc) if support_desc else "不限制"
            transparent_str = "透明" if proxy_info['transparent'] else "匿名"
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

if __name__ == '__main__':
    extract_proxies_menu()

```
