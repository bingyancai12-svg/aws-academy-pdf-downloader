"""
AWS Academy Student Guide PDF Downloader v11

支援任意 Module URL，可批次下載，自動從頁面標題產生檔名。

原理：
  進入深層 iframe (d4 frame)，透過輪詢 Performance API 等待 PDF.js
  實際載入的 PDF URL 出現，再用同源 fetch() 重新下載。

用法:
    python grab_student_guide_v11.py <URL1> [URL2] [URL3] ...
    python grab_student_guide_v11.py   # 互動式輸入 URL
"""

import os
import sys
import re
import time
import base64

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


def setup_driver():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    options = Options()
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def navigate_to_pdf_frame(driver):
    """進入 d4 frame (PDF viewer)：main -> [1] -> [0] -> [0] -> [0]"""
    driver.switch_to.default_content()
    for idx in [1, 0, 0, 0]:
        try:
            driver.switch_to.frame(idx)
        except Exception:
            return False
    return True


def sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name if name else "student_guide"


def search_pdf_in_all_frames(driver, depth=0, max_depth=6):
    """遞迴搜尋所有 frame 的 Performance entries 找 .pdf URL"""
    if depth > max_depth:
        return None

    try:
        pdf_url = driver.execute_script("""
            var entries = performance.getEntriesByType('resource');
            for (var i = 0; i < entries.length; i++) {
                if (entries[i].name.match(/\\.pdf(\\?|$)/i)) {
                    return entries[i].name;
                }
            }
            return null;
        """)
        if pdf_url:
            where = driver.execute_script("return window.location.href")
            print(f"    找到！在 {where[:80]}")
            return pdf_url
    except Exception:
        pass

    try:
        count = driver.execute_script(
            "return document.querySelectorAll('iframe').length") or 0
        for i in range(count):
            try:
                driver.switch_to.frame(i)
                result = search_pdf_in_all_frames(driver, depth + 1, max_depth)
                driver.switch_to.parent_frame()
                if result:
                    return result
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return None


def download_one(driver, url):
    """下載單一 URL 的 PDF"""
    print(f"\n{'='*60}")
    print(f"  目標: {url}")
    print("=" * 60)

    driver.get(url)
    print("等待頁面外框載入 (15 秒)...")
    time.sleep(15)

    # 進入 d4 frame
    if not navigate_to_pdf_frame(driver):
        print("  ❌ 無法進入 PDF viewer frame")
        return False, None

    title = ""
    pdf_url = None

    print("開始監聽網路載入 PDF... (最多等待 120 秒)")
    # 輪詢 24 次，每次等待 5 秒 = 最多 120 秒
    for attempt in range(24):
        info = driver.execute_script("""
            var result = {};

            // 標題
            var el = document.getElementById('rscpAu-ToolbarTitle');
            result.title = el ? el.textContent.trim() : (document.title || '');

            // Performance entries 找 .pdf
            var entries = performance.getEntriesByType('resource');
            result.pdfUrl = null;
            for (var i = 0; i < entries.length; i++) {
                var name = entries[i].name;
                if (name.match(/\\.pdf(\\?|$)/i)) {
                    result.pdfUrl = name;
                    break;
                }
            }
            return result;
        """)

        current_title = info.get("title", "")
        if current_title and not title:
            title = current_title
            print(f"  📌 取得文件標題: {title}")

        pdf_url = info.get("pdfUrl")
        if pdf_url:
            break
            
        # 如果還沒找到，等 5 秒再試
        time.sleep(5)

    filename = sanitize_filename(title) + ".pdf" if title else "student_guide.pdf"

    if not pdf_url:
        print(f"  ⚠ d4 frame 內未找到 PDF，嘗試從其他 frame 搜尋...")
        driver.switch_to.default_content()
        pdf_url = search_pdf_in_all_frames(driver)

        if pdf_url:
            # 切回能 fetch 該 url 的 frame
            navigate_to_pdf_frame(driver)

    if not pdf_url:
        print("  ❌ 所有 frame 都找不到 .pdf URL")
        return False, None

    print(f"  📎 找到 PDF URL: {pdf_url}")
    print(f"  檔名: {filename}")
    print("  下載中 (可能需要幾十秒)...")

    try:
        pdf_b64 = driver.execute_script("""
            var url = arguments[0];
            return fetch(url)
                .then(function(r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.arrayBuffer();
                })
                .then(function(buf) {
                    var bytes = new Uint8Array(buf);
                    var CHUNK = 8192, parts = [];
                    for (var i = 0; i < bytes.length; i += CHUNK) {
                        parts.push(String.fromCharCode.apply(null,
                            bytes.subarray(i, Math.min(i + CHUNK, bytes.length))));
                    }
                    return btoa(parts.join(''));
                });
        """, pdf_url)
    except Exception as e:
        print(f"  ❌ fetch 錯誤: {e}")
        return False, None

    if pdf_b64:
        pdf_data = base64.b64decode(pdf_b64)
        if pdf_data[:5] == b"%PDF-":
            fp = os.path.join(DOWNLOAD_DIR, filename)
            with open(fp, "wb") as f:
                f.write(pdf_data)
            print(f"\n  🎉 成功！({len(pdf_data) // 1024} KB) -> {fp}")
            return True, fp

    print("  ❌ 下載的資料不是有效的 PDF")
    return False, None


def parse_urls():
    if len(sys.argv) > 1:
        return sys.argv[1:]

    print("\n未提供 URL，進入互動模式。")
    print("請貼上 AWS Academy 頁面 URL（多個用空格或換行分隔，空行結束）:\n")
    urls = []
    while True:
        line = input(">>> ").strip()
        if not line:
            break
        urls.extend(line.split())
    return urls


def main():
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v11")
    print("  支援任意 Module，可批次下載")
    print("=" * 60)

    urls = parse_urls()
    if not urls:
        print("沒有提供任何 URL，結束。")
        return

    print(f"\n共 {len(urls)} 個目標")

    driver = setup_driver()
    try:
        driver.get("https://awsacademy.instructure.com/login")
        print("\n  👉 請在 Chrome 中登入 AWS Academy")
        print("  👉 登入完成後回到這裡按 Enter")
        input("\n>>> ")

        results = []
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}]")
            ok, fp = download_one(driver, url)
            results.append((url, ok, fp))

        print(f"\n{'='*60}")
        print(f"  下載結果 ({sum(r[1] for r in results)}/{len(results)} 成功)")
        print("=" * 60)
        for url, ok, fp in results:
            status = f"✅ {fp}" if ok else "❌ 失敗"
            print(f"  {status}")
            print(f"    {url}")

        input("\n按 Enter 關閉瀏覽器...")
    except KeyboardInterrupt:
        print("\n使用者中斷")
    except Exception as e:
        print(f"\n發生錯誤: {e}")
        import traceback
        traceback.print_exc()
        input("按 Enter 關閉...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
