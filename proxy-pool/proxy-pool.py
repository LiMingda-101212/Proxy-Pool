import csv

# ============配置区
OUTPUT_FILE = "proxies.csv"  # 输出有效代理文件


with open('proxies.csv','a') as f:
    writer = csv.writer(f)
    writer.writerow([1,1,1])
