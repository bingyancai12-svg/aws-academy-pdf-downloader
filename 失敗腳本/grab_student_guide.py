"""
AWS Academy Canvas - Student Guide PDF 下載工具

功能：
1. 開啟 Chrome 瀏覽器並導航到 AWS Academy 登入頁面
2. 等待你手動登入
3. 自動導航到 Student Guide 頁面
4. 深入 iframe 層級尋找 PDF 來源
5. 攔截並下載 PDF

使用方式：
    python grab_student_guide.py
"""

import os
import sys
import time
import json
import re
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============ 設定區 ============
COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = r"D:\antigravity\downloads"
# ================================


def setup_driver():
    """設定 Chrome driver，啟用 PDF 自動下載 & 網路攔截"""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    options = Options()

    # PDF 遇到時自動下載而非在瀏覽器中顯示
    prefs = {
        "plugins.always_open_pdf_externally": True,
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    # 啟用 Performance Logging 來攔截所有網路請求
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # 不要用 headless，因為需要手動登入
    # options.add_argument("--headless")

    driver = webdriver.Chrome(options=options)
    driver.maximize_window()

    # 啟用 CDP Network 監聽
    driver.execute_cdp_cmd("Network.enable", {})

    return driver


def wait_for_login(driver):
    """等待使用者手動登入"""
    print("\n" + "=" * 60)
    print("請在瀏覽器中完成登入")
    print("登入後頁面會自動跳轉，請等待...")
    print("=" * 60)

    # 等待直到 URL 不再是登入頁面
    while True:
        current_url = driver.current_url
        if "login" not in current_url.lower() and "sso" not in current_url.lower():
            # 可能已經登入了
            time.sleep(2)
            # 再確認一次
            if "login" not in driver.current_url.lower():
                break
        # 也檢查是否已經在課程頁面
        if "courses" in current_url:
            break
        time.sleep(1)

    print("✅ 登入成功！")
    time.sleep(2)


def collect_network_urls(driver):
    """從 Performance Log 中收集所有網路請求的 URL"""
    urls = set()
    try:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                if msg["method"] == "Network.requestWillBeSent":
                    url = msg["params"]["request"]["url"]
                    urls.add(url)
                elif msg["method"] == "Network.responseReceived":
                    url = msg["params"]["response"]["url"]
                    content_type = msg["params"]["response"].get("headers", {}).get("content-type", "")
                    if "pdf" in content_type.lower():
                        print(f"\n🎯 發現 PDF response: {url}")
                        urls.add(url)
            except (KeyError, json.JSONDecodeError):
                pass
    except Exception as e:
        print(f"  (無法取得 performance log: {e})")
    return urls


def explore_iframes(driver, depth=0, max_depth=5):
    """遞迴探索所有 iframe 層級，尋找 PDF 相關內容"""
    indent = "  " * depth
    results = []

    if depth > max_depth:
        return results

    try:
        current_url = driver.current_url
        print(f"{indent}📂 Frame URL: {current_url}")
    except Exception:
        print(f"{indent}📂 Frame (無法取得 URL)")

    # 搜尋當前 frame 中的 PDF 相關元素
    selectors_to_check = [
        ("a[href*='pdf']", "href"),
        ("a[href*='download']", "href"),
        ("a[href*='s3']", "href"),
        ("a[href*='cloudfront']", "href"),
        ("embed", "src"),
        ("object", "data"),
        ("iframe", "src"),
        ("a[href*='file']", "href"),
        ("[data-download-url]", "data-download-url"),
        ("[data-url]", "data-url"),
    ]

    for selector, attr in selectors_to_check:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                url = el.get_attribute(attr)
                if url and url != "about:blank":
                    tag = el.tag_name
                    print(f"{indent}  🔗 <{tag}> {attr}={url}")
                    results.append({"tag": tag, "attr": attr, "url": url, "depth": depth})
        except Exception:
            pass

    # 嘗試用 JS 取得更多資訊
    try:
        js_result = driver.execute_script("""
            var results = [];
            // 找所有可能的 PDF URL
            var html = document.documentElement.innerHTML;
            
            // 找 PDF 直接連結
            var pdfMatches = html.match(/https?:\\/\\/[^\\s"'<>]+\\.pdf[^\\s"'<>]*/gi);
            if (pdfMatches) pdfMatches.forEach(function(m) { results.push('PDF_URL: ' + m); });
            
            // 找 S3 連結
            var s3Matches = html.match(/https?:\\/\\/[^\\s"'<>]*s3[^\\s"'<>]*amazonaws[^\\s"'<>]*/gi);
            if (s3Matches) s3Matches.forEach(function(m) { results.push('S3_URL: ' + m); });
            
            // 找 download 連結
            var dlMatches = html.match(/https?:\\/\\/[^\\s"'<>]*download[^\\s"'<>]*/gi);
            if (dlMatches) dlMatches.forEach(function(m) { results.push('DL_URL: ' + m); });
            
            // 找 readfile 連結 (Vocareum 常用)
            var rfMatches = html.match(/https?:\\/\\/[^\\s"'<>]*readfile[^\\s"'<>]*/gi);
            if (rfMatches) rfMatches.forEach(function(m) { results.push('RF_URL: ' + m); });

            // 找 blob URL
            var blobMatches = html.match(/blob:https?:\\/\\/[^\\s"'<>]*/gi);
            if (blobMatches) blobMatches.forEach(function(m) { results.push('BLOB_URL: ' + m); });
            
            // 找 canvas file 連結
            var fileMatches = html.match(/\\/files\\/\\d+\\/download/gi);
            if (fileMatches) fileMatches.forEach(function(m) { results.push('FILE_URL: ' + m); });
            
            // 找 Vocareum 相關連結
            var vocMatches = html.match(/https?:\\/\\/[^\\s"'<>]*vocareum[^\\s"'<>]*/gi);
            if (vocMatches) vocMatches.forEach(function(m) { results.push('VOC_URL: ' + m); });
            
            return results;
        """)
        if js_result:
            for r in set(js_result):
                print(f"{indent}  🔍 {r}")
                results.append({"tag": "js", "attr": "match", "url": r, "depth": depth})
    except Exception as e:
        print(f"{indent}  (JS 搜尋失敗: {e})")

    # 遞迴進入子 iframe
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, iframe in enumerate(iframes):
            src = iframe.get_attribute("src") or "(no src)"
            print(f"{indent}  📌 發現 iframe[{i}]: {src}")
            try:
                driver.switch_to.frame(iframe)
                sub_results = explore_iframes(driver, depth + 1, max_depth)
                results.extend(sub_results)
                driver.switch_to.parent_frame()
            except Exception as e:
                print(f"{indent}    ❌ 無法進入 iframe: {e}")
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return results


def try_download_pdf(driver, url):
    """嘗試下載 PDF"""
    print(f"\n⬇️  嘗試下載: {url}")

    # 方法 1：用 Selenium 的 cookie 透過 urllib 下載
    try:
        cookies = driver.get_cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        req = urllib.request.Request(url)
        req.add_header("Cookie", cookie_str)
        req.add_header("User-Agent", driver.execute_script("return navigator.userAgent"))

        response = urllib.request.urlopen(req, timeout=30)
        content_type = response.headers.get("Content-Type", "")

        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            filename = "student_guide.pdf"
            # 嘗試從 Content-Disposition 取得檔名
            cd = response.headers.get("Content-Disposition", "")
            if "filename" in cd:
                match = re.search(r'filename[^;=\n]*=((["\']).*?\2|[^\s;]+)', cd)
                if match:
                    filename = match.group(1).strip('"\'')

            filepath = os.path.join(DOWNLOAD_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(response.read())
            print(f"✅ PDF 下載成功: {filepath}")
            return filepath
        else:
            print(f"  ⚠️ Content-Type 不是 PDF: {content_type}")
            # 可能是重定向到實際 PDF，嘗試儲存看看
            data = response.read()
            if data[:5] == b"%PDF-":
                filepath = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                with open(filepath, "wb") as f:
                    f.write(data)
                print(f"✅ PDF 下載成功（從二進位內容確認）: {filepath}")
                return filepath
    except Exception as e:
        print(f"  ❌ urllib 下載失敗: {e}")

    # 方法 2：讓 Selenium 直接導航到 URL（會觸發自動下載）
    try:
        driver.execute_script(f"window.open('{url}', '_blank');")
        time.sleep(5)
        # 檢查下載目錄
        files = list(Path(DOWNLOAD_DIR).glob("*.pdf"))
        if files:
            newest = max(files, key=lambda f: f.stat().st_mtime)
            print(f"✅ PDF 已下載到: {newest}")
            return str(newest)
    except Exception as e:
        print(f"  ❌ 瀏覽器下載失敗: {e}")

    return None


def use_cdp_to_intercept(driver):
    """使用 Chrome DevTools Protocol 攔截網路請求中的 PDF"""
    print("\n🔎 使用 CDP 攔截網路請求...")
    pdf_urls = []

    try:
        # 取得所有網路請求
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                method = msg.get("method", "")

                if method == "Network.responseReceived":
                    resp = msg["params"]["response"]
                    url = resp.get("url", "")
                    mime = resp.get("mimeType", "")
                    content_type = resp.get("headers", {}).get("content-type", "")

                    if "pdf" in mime.lower() or "pdf" in content_type.lower() or ".pdf" in url.lower():
                        print(f"  🎯 PDF 請求: {url}")
                        pdf_urls.append(url)

                    # 也找大型檔案（可能是 PDF）
                    content_length = resp.get("headers", {}).get("content-length", "0")
                    try:
                        size = int(content_length)
                        if size > 500000:  # > 500KB
                            print(f"  📦 大型檔案 ({size // 1024}KB): {url}")
                            if "vocareum" in url or "s3" in url or "cloudfront" in url:
                                pdf_urls.append(url)
                    except (ValueError, TypeError):
                        pass

                elif method == "Network.requestWillBeSent":
                    url = msg["params"]["request"].get("url", "")
                    if ".pdf" in url.lower() or "download" in url.lower():
                        if "vocareum" in url or "s3" in url:
                            print(f"  🎯 PDF 請求: {url}")
                            pdf_urls.append(url)

            except (KeyError, json.JSONDecodeError):
                pass
    except Exception as e:
        print(f"  CDP 攔截失敗: {e}")

    return list(set(pdf_urls))


def main():
    print("🚀 AWS Academy Student Guide PDF 下載工具")
    print(f"📁 下載目錄: {DOWNLOAD_DIR}")
    print()

    driver = setup_driver()

    try:
        # Step 1: 導航到登入頁面
        print("📖 正在打開 AWS Academy...")
        driver.get("https://awsacademy.instructure.com/login")
        time.sleep(2)

        # Step 2: 等待手動登入
        wait_for_login(driver)

        # Step 3: 導航到目標頁面
        print(f"\n📖 正在導航到 Student Guide 頁面...")
        driver.get(COURSE_URL)

        # 等待頁面載入
        print("⏳ 等待頁面載入（最多 30 秒）...")
        time.sleep(10)

        # 等待 iframe 載入
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )
            print("✅ 頁面已載入")
        except Exception:
            print("⚠️ 等待逾時，繼續嘗試...")

        # 再多等一下讓 LTI 完成載入
        print("⏳ 等待 LTI 內容載入...")
        time.sleep(10)

        # Step 4: 用 CDP 攔截已發生的網路請求
        pdf_urls = use_cdp_to_intercept(driver)

        # Step 5: 探索 iframe 結構
        print("\n" + "=" * 60)
        print("🔍 開始探索 iframe 結構...")
        print("=" * 60)

        driver.switch_to.default_content()
        iframe_results = explore_iframes(driver)

        # 收集所有可能的 PDF URL
        all_urls = set(pdf_urls)
        for r in iframe_results:
            url = r["url"]
            # 清理 URL
            for prefix in ["PDF_URL: ", "S3_URL: ", "DL_URL: ", "RF_URL: ",
                           "BLOB_URL: ", "FILE_URL: ", "VOC_URL: "]:
                if url.startswith(prefix):
                    url = url[len(prefix):]
            if any(keyword in url.lower() for keyword in
                   [".pdf", "download", "s3.", "cloudfront", "readfile", "files/"]):
                all_urls.add(url)

        # Step 6: 嘗試下載找到的 URL
        if all_urls:
            print(f"\n{'=' * 60}")
            print(f"📋 找到 {len(all_urls)} 個可能的 PDF URL:")
            print("=" * 60)
            for i, url in enumerate(all_urls, 1):
                print(f"  [{i}] {url}")

            driver.switch_to.default_content()
            for url in all_urls:
                result = try_download_pdf(driver, url)
                if result:
                    print(f"\n🎉 成功下載 PDF: {result}")
                    break
            else:
                print("\n⚠️ 自動下載未成功。請嘗試手動打開上面的 URL。")
        else:
            print("\n⚠️ 未找到 PDF URL")

        # Step 7: 額外嘗試 - 收集 Network log 中的所有 URL
        print(f"\n{'=' * 60}")
        print("📋 所有攔截到的網路請求（按域名分類）:")
        print("=" * 60)
        all_network_urls = collect_network_urls(driver)

        # 按域名分類顯示
        domains = {}
        for url in all_network_urls:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain not in domains:
                    domains[domain] = []
                domains[domain].append(url)
            except Exception:
                pass

        interesting_domains = ["vocareum", "s3.", "cloudfront", "amazonaws"]
        for domain, urls in sorted(domains.items()):
            if any(kw in domain for kw in interesting_domains):
                print(f"\n  🌐 {domain}:")
                for url in urls[:10]:
                    print(f"    {url}")

        print(f"\n{'=' * 60}")
        print("完成！如果 PDF 沒有自動下載，請查看上面的 URL 列表")
        print(f"按 Enter 關閉瀏覽器...")
        print("=" * 60)
        input()

    except KeyboardInterrupt:
        print("\n\n⚠️ 使用者中斷")
    except Exception as e:
        print(f"\n❌ 發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        input("按 Enter 關閉...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
