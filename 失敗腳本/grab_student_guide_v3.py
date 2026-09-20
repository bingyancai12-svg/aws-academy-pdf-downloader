"""
AWS Academy Student Guide PDF 下載工具 (v3)

全自動版：自動啟動 Chrome（帶 debugging port），你只需要登入。
"""

import os
import sys
import time
import json
import re
import subprocess
import urllib.request
import base64
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============ 設定區 ============
COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = r"D:\antigravity\downloads"
DEBUG_PORT = 9222
# ================================


def find_chrome():
    possible = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in possible:
        if os.path.exists(p):
            return p
    return None


def kill_chrome():
    """關閉所有 Chrome 進程"""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                       capture_output=True, timeout=10)
        time.sleep(2)
    except Exception:
        pass


def start_chrome_debug(chrome_path):
    """啟動帶 remote debugging 的 Chrome"""
    user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    cmd = [
        chrome_path,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={user_data}",
        "https://awsacademy.instructure.com/login"
    ]
    # 用 Popen 在背景啟動
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    return proc


def connect_chrome():
    """連接到已開啟的 Chrome"""
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
    driver = webdriver.Chrome(options=options)
    return driver


def explore_iframes(driver, depth=0, max_depth=5):
    """遞迴探索所有 iframe 層級"""
    indent = "  " * depth
    results = []
    if depth > max_depth:
        return results

    try:
        current_url = driver.current_url
        print(f"{indent}[Frame] URL: {current_url}")
    except Exception:
        print(f"{indent}[Frame] (cannot get URL)")

    # JS 搜尋當前 frame
    try:
        js_result = driver.execute_script(r"""
            var results = [];
            var html = document.documentElement.innerHTML;
            
            var patterns = [
                [/https?:\/\/[^\s"'<>]+\.pdf[^\s"'<>]*/gi, 'PDF'],
                [/https?:\/\/[^\s"'<>]*s3[^\s"'<>]*amazonaws[^\s"'<>]*/gi, 'S3'],
                [/https?:\/\/[^\s"'<>]*\/download[^\s"'<>]*/gi, 'DL'],
                [/https?:\/\/[^\s"'<>]*readfile[^\s"'<>]*/gi, 'RF'],
                [/https?:\/\/[^\s"'<>]*vocareum[^\s"'<>]*/gi, 'VOC'],
            ];
            
            patterns.forEach(function(p) {
                var matches = html.match(p[0]);
                if (matches) matches.forEach(function(m) { results.push(p[1] + ': ' + m); });
            });
            
            // CloudFront (排除 Canvas CDN)
            var cfMatches = html.match(/https?:\/\/[^\s"'<>]*cloudfront[^\s"'<>]*/gi);
            if (cfMatches) cfMatches.forEach(function(m) {
                if (m.indexOf('du11hjcvx0uqb') === -1) results.push('CF: ' + m);
            });

            // Canvas files
            var fileMatches = html.match(/\/files\/\d+/g);
            if (fileMatches) fileMatches.forEach(function(m) { results.push('FILE: ' + m); });
            
            // embed/object
            document.querySelectorAll('embed, object').forEach(function(el) {
                var src = el.src || el.data;
                if (src) results.push('EMBED: ' + src);
            });
            
            // All anchors with interesting hrefs
            document.querySelectorAll('a').forEach(function(a) {
                if (a.href && (a.href.indexOf('.pdf') !== -1 || a.href.indexOf('download') !== -1))
                    results.push('LINK: ' + a.href);
            });
            
            return [...new Set(results)];
        """)
        if js_result:
            for r in js_result:
                print(f"{indent}  >> {r}")
                results.append(r)
    except Exception as e:
        print(f"{indent}  (JS search failed: {e})")

    # 遞迴進入子 iframe
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, iframe in enumerate(iframes):
            src = iframe.get_attribute("src") or ""
            if src == "about:blank" or not src:
                continue
            print(f"{indent}  -> iframe[{i}]: {src[:100]}")
            try:
                driver.switch_to.frame(iframe)
                sub = explore_iframes(driver, depth + 1, max_depth)
                results.extend(sub)
                driver.switch_to.parent_frame()
            except Exception as e:
                print(f"{indent}     (cannot enter: {e})")
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return results


def download_url(driver, url):
    """嘗試用 cookie 下載 URL"""
    # 清理 prefix
    for prefix in ["PDF: ", "S3: ", "DL: ", "RF: ", "VOC: ", "CF: ", "FILE: ", "LINK: ", "EMBED: "]:
        if url.startswith(prefix):
            url = url[len(prefix):]
            break

    if url.startswith("/"):
        url = "https://awsacademy.instructure.com" + url

    print(f"\n  Trying: {url[:120]}")

    try:
        cookies = driver.get_cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        req = urllib.request.Request(url)
        req.add_header("Cookie", cookie_str)
        req.add_header("User-Agent", driver.execute_script("return navigator.userAgent"))

        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()

        if data[:5] == b"%PDF-":
            filename = "student_guide.pdf"
            cd = resp.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";\n]+)"?', cd)
            if m:
                filename = m.group(1).strip()
            filepath = os.path.join(DOWNLOAD_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(data)
            print(f"  SUCCESS! Saved ({len(data)//1024} KB): {filepath}")
            return filepath
        else:
            print(f"  Not PDF (Content-Type: {resp.headers.get('Content-Type', '?')})")
    except Exception as e:
        print(f"  Failed: {e}")
    return None


def print_page_as_pdf(driver):
    """用 CDP 把頁面列印成 PDF 作為備用方案"""
    print("\n  Using CDP Page.printToPDF as fallback...")
    try:
        result = driver.execute_cdp_cmd("Page.printToPDF", {
            "landscape": False,
            "printBackground": True,
            "preferCSSPageSize": True,
        })
        pdf_data = base64.b64decode(result["data"])
        filepath = os.path.join(DOWNLOAD_DIR, "student_guide_print.pdf")
        with open(filepath, "wb") as f:
            f.write(pdf_data)
        print(f"  Saved print PDF ({len(pdf_data)//1024} KB): {filepath}")
        return filepath
    except Exception as e:
        print(f"  Print failed: {e}")
    return None


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v3")
    print("=" * 60)

    chrome_path = find_chrome()
    if not chrome_path:
        print("ERROR: Chrome not found")
        return

    print(f"Chrome: {chrome_path}")

    # 關閉現有 Chrome 並以 debug 模式重啟
    print("\nClosing existing Chrome...")
    kill_chrome()

    print(f"Starting Chrome with debug port {DEBUG_PORT}...")
    chrome_proc = start_chrome_debug(chrome_path)

    print("\n" + "=" * 60)
    print("Chrome 已開啟！")
    print("請在 Chrome 中完成 AWS Academy 登入")
    print("登入後回到這裡按 Enter")
    print("=" * 60)
    input("\n>>> 登入完成後按 Enter...")

    # 連接
    print("\nConnecting to Chrome...")
    try:
        driver = connect_chrome()
        print(f"Connected! Current page: {driver.current_url}")
    except Exception as e:
        print(f"ERROR connecting: {e}")
        return

    # 導航
    print(f"\nNavigating to Student Guide...")
    driver.get(COURSE_URL)

    print("Waiting for page load (5s)...")
    time.sleep(5)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "iframe"))
        )
    except Exception:
        pass

    print("Waiting for LTI content (20s)...")
    time.sleep(20)

    # 探索
    print(f"\n{'=' * 60}")
    print("Exploring iframe structure...")
    print("=" * 60)

    driver.switch_to.default_content()
    results = explore_iframes(driver)

    # 如果第一次沒找到，重試
    if not results:
        print("\nNothing found, waiting and retrying (15s)...")
        time.sleep(15)
        driver.switch_to.default_content()
        results = explore_iframes(driver)

    # 篩選 PDF 候選
    pdf_candidates = []
    other_candidates = []
    for r in results:
        rl = r.lower()
        if ".pdf" in rl or "readfile" in rl:
            pdf_candidates.append(r)
        elif "download" in rl or "s3.amazonaws" in rl:
            other_candidates.append(r)

    all_candidates = pdf_candidates + other_candidates

    if all_candidates:
        print(f"\n{'=' * 60}")
        print(f"Found {len(all_candidates)} candidate URLs")
        print("=" * 60)

        driver.switch_to.default_content()
        for c in all_candidates:
            fp = download_url(driver, c)
            if fp:
                print(f"\n{'=' * 60}")
                print(f"PDF downloaded: {fp}")
                print("=" * 60)
                input("\nPress Enter to exit...")
                return
        print("\nDirect download failed, trying print fallback...")

    # Fallback: CDP print
    print(f"\n{'=' * 60}")
    print("Trying Page.printToPDF fallback...")
    print("=" * 60)

    driver.switch_to.default_content()

    # 先嘗試列印主頁面
    fp = print_page_as_pdf(driver)

    # 也嘗試進入 iframe 後列印
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for i, iframe in enumerate(iframes):
        src = iframe.get_attribute("src") or ""
        if not src or src == "about:blank":
            continue
        try:
            driver.switch_to.frame(iframe)
            # 嘗試再深入一層
            inner_iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for j, inner in enumerate(inner_iframes):
                inner_src = inner.get_attribute("src") or ""
                if not inner_src or inner_src == "about:blank":
                    continue
                try:
                    driver.switch_to.frame(inner)
                    fp2 = print_page_as_pdf(driver)
                    if fp2:
                        fp = fp2
                    driver.switch_to.parent_frame()
                except Exception:
                    driver.switch_to.parent_frame()
            driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()

    if fp:
        print(f"\n{'=' * 60}")
        print(f"PDF saved: {fp}")
        print("(Note: this is a print version, not the original PDF)")
        print("=" * 60)
    else:
        print("\nAll methods failed.")
        if results:
            print("\nAll URLs found:")
            for i, r in enumerate(results, 1):
                print(f"  [{i}] {r}")

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
