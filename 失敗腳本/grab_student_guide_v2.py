"""
AWS Academy Student Guide PDF 下載工具 (v2)

改進版：連接到你已經開啟的 Chrome 瀏覽器，不需要重新登入。

使用前準備：
1. 關閉所有 Chrome 視窗
2. 用以下命令啟動 Chrome（啟用遠端除錯）：
   
   Windows:
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

   啟動後在 Chrome 中登入 AWS Academy
3. 登入完成後，回到終端機按 Enter 繼續

使用方式：
    python grab_student_guide_v2.py
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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============ 設定區 ============
COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = r"D:\antigravity\downloads"
# ================================


def find_chrome_path():
    """尋找 Chrome 安裝路徑"""
    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p
    return None


def setup_driver_remote():
    """連接到已開啟的 Chrome（remote debugging mode）"""
    options = Options()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    driver = webdriver.Chrome(options=options)
    return driver


def setup_driver_with_profile():
    """使用你現有的 Chrome profile 啟動（保留登入狀態）"""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    chrome_path = find_chrome_path()
    options = Options()

    if chrome_path:
        options.binary_location = chrome_path

    # 使用預設的 Chrome profile（保留已登入的 session）
    user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    if os.path.exists(user_data_dir):
        # 使用臨時 profile 避免衝突，但複製 cookies
        # 改用 remote debugging 模式更好
        pass

    # PDF 遇到時自動下載
    prefs = {
        "plugins.always_open_pdf_externally": True,
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
    }
    options.add_experimental_option("prefs", prefs)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def explore_iframes(driver, depth=0, max_depth=5):
    """遞迴探索所有 iframe 層級"""
    indent = "  " * depth
    results = []

    if depth > max_depth:
        return results

    try:
        current_url = driver.current_url
        print(f"{indent}📂 Frame URL: {current_url}")
    except Exception:
        print(f"{indent}📂 Frame (無法取得 URL)")

    # 用 JS 在當前 frame 中搜尋所有可能的 URL
    try:
        js_result = driver.execute_script("""
            var results = [];
            var html = document.documentElement.innerHTML;
            
            // PDF 直接連結
            var pdfMatches = html.match(/https?:\\/\\/[^\\s"'<>]+\\.pdf[^\\s"'<>]*/gi);
            if (pdfMatches) pdfMatches.forEach(function(m) { results.push('PDF: ' + m); });
            
            // S3 連結
            var s3Matches = html.match(/https?:\\/\\/[^\\s"'<>]*s3[^\\s"'<>]*amazonaws[^\\s"'<>]*/gi);
            if (s3Matches) s3Matches.forEach(function(m) { results.push('S3: ' + m); });
            
            // download 連結
            var dlMatches = html.match(/https?:\\/\\/[^\\s"'<>]*\\/download[^\\s"'<>]*/gi);
            if (dlMatches) dlMatches.forEach(function(m) { results.push('DL: ' + m); });
            
            // readfile (Vocareum)
            var rfMatches = html.match(/https?:\\/\\/[^\\s"'<>]*readfile[^\\s"'<>]*/gi);
            if (rfMatches) rfMatches.forEach(function(m) { results.push('RF: ' + m); });
            
            // Vocareum 連結
            var vocMatches = html.match(/https?:\\/\\/[^\\s"'<>]*vocareum[^\\s"'<>]*/gi);
            if (vocMatches) vocMatches.forEach(function(m) { results.push('VOC: ' + m); });
            
            // CloudFront 連結 (排除 Canvas 自身的 CDN)
            var cfMatches = html.match(/https?:\\/\\/[^\\s"'<>]*cloudfront[^\\s"'<>]*/gi);
            if (cfMatches) cfMatches.forEach(function(m) {
                if (m.indexOf('du11hjcvx0uqb') === -1) results.push('CF: ' + m);
            });

            // Canvas files 連結
            var fileMatches = html.match(/\\/files\\/\\d+/g);
            if (fileMatches) fileMatches.forEach(function(m) { results.push('FILE: ' + m); });
            
            // 所有 anchor 的 href
            document.querySelectorAll('a').forEach(function(a) {
                var href = a.href;
                if (href && (href.indexOf('pdf') !== -1 || href.indexOf('download') !== -1 || 
                    href.indexOf('s3') !== -1 || href.indexOf('file') !== -1)) {
                    results.push('A_HREF: ' + href);
                }
            });
            
            // embed/object
            document.querySelectorAll('embed, object').forEach(function(el) {
                var src = el.src || el.data;
                if (src) results.push('EMBED: ' + src);
            });
            
            return [...new Set(results)];
        """)
        if js_result:
            for r in js_result:
                print(f"{indent}  🔍 {r}")
                results.append(r)
    except Exception as e:
        print(f"{indent}  ⚠️ JS 搜尋失敗: {e}")

    # 遞迴進入子 iframe
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, iframe in enumerate(iframes):
            src = iframe.get_attribute("src") or "(no src)"
            if src == "about:blank":
                continue
            print(f"{indent}  📌 iframe[{i}]: {src[:100]}...")
            try:
                driver.switch_to.frame(iframe)
                sub_results = explore_iframes(driver, depth + 1, max_depth)
                results.extend(sub_results)
                driver.switch_to.parent_frame()
            except Exception as e:
                print(f"{indent}    ❌ 無法進入: {e}")
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return results


def try_download(driver, url):
    """嘗試下載檔案"""
    # 清理 URL prefix
    for prefix in ["PDF: ", "S3: ", "DL: ", "RF: ", "VOC: ", "CF: ", "FILE: ", "A_HREF: ", "EMBED: "]:
        if url.startswith(prefix):
            url = url[len(prefix):]
            break

    if url.startswith("/"):
        url = "https://awsacademy.instructure.com" + url

    print(f"\n⬇️  嘗試下載: {url[:120]}...")

    try:
        cookies = driver.get_cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        req = urllib.request.Request(url)
        req.add_header("Cookie", cookie_str)
        req.add_header("User-Agent", driver.execute_script("return navigator.userAgent"))

        response = urllib.request.urlopen(req, timeout=30)
        data = response.read()

        if data[:5] == b"%PDF-":
            # 嘗試從 header 取得檔名
            filename = "student_guide.pdf"
            cd = response.headers.get("Content-Disposition", "")
            match = re.search(r'filename[^;=\n]*=([\"\']?)(.+?)\1(;|$)', cd)
            if match:
                filename = match.group(2)

            filepath = os.path.join(DOWNLOAD_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(data)
            size_mb = len(data) / 1024 / 1024
            print(f"  ✅ 下載成功！ ({size_mb:.1f} MB)")
            print(f"  📁 儲存至: {filepath}")
            return filepath
        else:
            content_type = response.headers.get("Content-Type", "unknown")
            print(f"  ⚠️ 不是 PDF (Content-Type: {content_type})")
            # 如果是 HTML，可能是重定向頁面，印出前 500 字元幫助 debug
            if b"<html" in data[:200].lower():
                print(f"  📄 HTML 內容: {data[:300].decode('utf-8', errors='replace')}")
    except Exception as e:
        print(f"  ❌ 下載失敗: {e}")

    return None


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    print("=" * 60)
    print("  AWS Academy Student Guide PDF 下載工具 (v2)")
    print("=" * 60)
    print()

    chrome_path = find_chrome_path()
    if not chrome_path:
        print("❌ 找不到 Chrome，請手動指定路徑")
        return

    print(f"✅ 找到 Chrome: {chrome_path}")
    print()
    print("📋 請按照以下步驟操作：")
    print()
    print("  1. 先關閉所有 Chrome 視窗")
    print("  2. 用以下命令啟動 Chrome：")
    print()
    print(f'     "{chrome_path}" --remote-debugging-port=9222')
    print()
    print("  3. 在開啟的 Chrome 中登入 AWS Academy")
    print("  4. 登入完成後回到這裡按 Enter")
    print()
    input("👉 準備好了嗎？按 Enter 繼續...")

    # 連接到已開啟的 Chrome
    print("\n🔗 正在連接到 Chrome...")
    try:
        driver = setup_driver_remote()
        print(f"✅ 已連接！目前頁面: {driver.current_url}")
    except Exception as e:
        print(f"❌ 無法連接到 Chrome: {e}")
        print("   請確認你已經用 --remote-debugging-port=9222 啟動 Chrome")
        return

    try:
        # 導航到目標頁面
        print(f"\n📖 正在導航到 Student Guide...")
        driver.get(COURSE_URL)

        print("⏳ 等待頁面載入...")
        time.sleep(5)

        # 等待 iframe 出現
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )
        except Exception:
            pass

        # 再多等讓 LTI 載入
        print("⏳ 等待 LTI 內容載入（15 秒）...")
        time.sleep(15)

        # 探索 iframe 結構
        print(f"\n{'=' * 60}")
        print("🔍 探索 iframe 結構與搜尋 PDF URL...")
        print("=" * 60)

        driver.switch_to.default_content()
        results = explore_iframes(driver)

        if not results:
            print("\n⚠️ 第一次掃描沒找到，等待更多載入後重試...")
            time.sleep(10)
            driver.switch_to.default_content()
            results = explore_iframes(driver)

        # 篩選可能的 PDF URL
        pdf_candidates = []
        for r in results:
            url = r
            for prefix in ["PDF: ", "S3: ", "DL: ", "RF: ", "EMBED: ", "A_HREF: ", "CF: "]:
                if r.startswith(prefix):
                    url = r[len(prefix):]
                    break
            if any(kw in url.lower() for kw in [".pdf", "download", "readfile", "s3.amazonaws"]):
                pdf_candidates.append(r)

        # 如果沒有明確的 PDF，也試試其他連結
        if not pdf_candidates:
            pdf_candidates = [r for r in results if not r.startswith("FILE: ")]

        if pdf_candidates:
            print(f"\n{'=' * 60}")
            print(f"📋 找到 {len(pdf_candidates)} 個候選 URL，開始嘗試下載...")
            print("=" * 60)

            driver.switch_to.default_content()
            for candidate in pdf_candidates:
                filepath = try_download(driver, candidate)
                if filepath:
                    print(f"\n🎉🎉🎉 成功！PDF 已儲存至: {filepath}")
                    break
            else:
                print("\n⚠️ 自動下載未成功。")
                print("\n📋 所有找到的 URL：")
                for i, r in enumerate(results, 1):
                    print(f"  [{i}] {r}")
                print("\n你可以手動在 Chrome 中試試這些 URL。")
        else:
            print("\n⚠️ 未找到任何 PDF 相關 URL")
            print("\n嘗試最後手段：頁面截圖 + 列印為 PDF...")

            # 嘗試用 Chrome print to PDF (CDP)
            try:
                driver.switch_to.default_content()
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    src = iframe.get_attribute("src") or ""
                    if "vocareum" in src or "sso" in src:
                        driver.switch_to.frame(iframe)
                        # 繼續深入
                        inner_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                        for inner in inner_iframes:
                            try:
                                driver.switch_to.frame(inner)
                                # 在最內層用 CDP 列印
                                break
                            except Exception:
                                pass
                        break

                # 用 CDP 列印整個頁面為 PDF
                driver.switch_to.default_content()
                result = driver.execute_cdp_cmd("Page.printToPDF", {
                    "landscape": False,
                    "printBackground": True,
                    "preferCSSPageSize": True,
                })
                
                import base64
                pdf_data = base64.b64decode(result["data"])
                filepath = os.path.join(DOWNLOAD_DIR, "student_guide_print.pdf")
                with open(filepath, "wb") as f:
                    f.write(pdf_data)
                print(f"\n✅ 已用列印方式儲存 PDF: {filepath}")
                print("   （注意：這是頁面列印版，不是原始 PDF）")

            except Exception as e:
                print(f"\n❌ 列印也失敗了: {e}")

        print(f"\n{'=' * 60}")
        print("完成！")
        print(f"📁 下載目錄: {DOWNLOAD_DIR}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n⚠️ 使用者中斷")
    except Exception as e:
        print(f"\n❌ 發生錯誤: {e}")
        import traceback
        traceback.print_exc()

    # 不關閉瀏覽器（因為是連接到使用者的 Chrome）
    print("\n瀏覽器保持開啟，你可以繼續使用。")
    input("按 Enter 結束程式...")


if __name__ == "__main__":
    main()
