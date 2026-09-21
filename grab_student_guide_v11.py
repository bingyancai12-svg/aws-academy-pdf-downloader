"""
AWS Academy Student Guide PDF Downloader v11

支援任意 Module URL，可批次下載，自動從頁面標題產生檔名。

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

HOOK_SCRIPT = """
(function() {
    let _pdfjsLib = window.pdfjsLib;
    Object.defineProperty(window, 'pdfjsLib', {
        configurable: true,
        enumerable: true,
        get: function() { return _pdfjsLib; },
        set: function(val) {
            _pdfjsLib = val;
            if (val && val.getDocument && !val._isHooked) {
                val._isHooked = true;
                const origGetDocument = val.getDocument;
                val.getDocument = function() {
                    const task = origGetDocument.apply(this, arguments);
                    task.promise.then(pdfDoc => {
                        window.__interceptedPDFDoc = pdfDoc;
                    }).catch(e => {});
                    return task;
                };
            }
        }
    });

    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this._url = url;
        origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        this.addEventListener('load', function() {
            try {
                if (this.responseText && this.responseText.substring(0,4) === '%PDF') {
                    window.__interceptedRawPDF = this.responseText;
                }
            } catch(e) {}
        });
        origSend.apply(this, arguments);
    };
})();
"""


def setup_driver():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    options = Options()
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": HOOK_SCRIPT})
    return driver


def get_page_title(driver):
    """從 d4 frame 的 <title> 取得文件代號作為檔名"""
    driver.switch_to.default_content()
    # 路徑: main -> iframe[1] -> iframe[0] -> iframe[0] -> iframe[0]
    path = [1, 0, 0, 0]
    for idx in path:
        try:
            driver.switch_to.frame(idx)
        except Exception:
            break

    try:
        title = driver.execute_script("return document.title || ''")
    except Exception:
        title = ""

    driver.switch_to.default_content()
    return title.strip()


def sanitize_filename(name):
    """移除不合法的檔名字元"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name if name else "student_guide"


def extract_from_frames(driver, depth=0, max_depth=6):
    """遞迴搜尋所有 frame，提取被 Hook 攔截到的 PDF"""
    if depth > max_depth:
        return None

    indent = "  " * depth
    try:
        url = driver.execute_script("return window.location.href")
        print(f"{indent}[Frame] {url[:100]}")

        if driver.execute_script("return !!window.__interceptedPDFDoc;"):
            print(f"{indent}🎯 找到 PDFDocument，正在提取...")
            pdf_b64 = driver.execute_script("""
                return window.__interceptedPDFDoc.getData().then(function(data) {
                    var bytes = new Uint8Array(data);
                    var CHUNK = 8192, parts = [];
                    for (var i = 0; i < bytes.byteLength; i += CHUNK) {
                        parts.push(String.fromCharCode.apply(null,
                            bytes.subarray(i, Math.min(i + CHUNK, bytes.byteLength))));
                    }
                    return btoa(parts.join(''));
                });
            """)
            if pdf_b64:
                return base64.b64decode(pdf_b64)

        if driver.execute_script("return !!window.__interceptedRawPDF;"):
            print(f"{indent}🎯 找到 Raw PDF")
            raw = driver.execute_script("return window.__interceptedRawPDF;")
            return raw.encode('latin1')
    except Exception:
        pass

    try:
        count = driver.execute_script("return document.querySelectorAll('iframe').length") or 0
        for i in range(count):
            try:
                driver.switch_to.frame(i)
                data = extract_from_frames(driver, depth + 1, max_depth)
                driver.switch_to.parent_frame()
                if data:
                    return data
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return None


def download_one(driver, url):
    """下載單一 URL 的 PDF，回傳 (成功?, 檔案路徑)"""
    print(f"\n{'='*60}")
    print(f"  目標: {url}")
    print("=" * 60)

    driver.get(url)
    print("等待頁面與 PDF 完全載入 (30 秒)...")
    time.sleep(30)

    # 取得檔名
    title = get_page_title(driver)
    filename = sanitize_filename(title) + ".pdf" if title else "student_guide.pdf"
    print(f"  文件標題: {title or '(未知)'}")
    print(f"  檔名: {filename}")

    # 提取 PDF
    driver.switch_to.default_content()
    pdf_data = extract_from_frames(driver)

    if pdf_data and pdf_data[:5] == b"%PDF-":
        fp = os.path.join(DOWNLOAD_DIR, filename)
        with open(fp, "wb") as f:
            f.write(pdf_data)
        print(f"\n🎉 成功！({len(pdf_data)//1024} KB) -> {fp}")
        return True, fp
    else:
        print("\n❌ 提取失敗")
        return False, None


def parse_urls():
    """從命令列參數或互動式輸入取得 URL 列表"""
    if len(sys.argv) > 1:
        return sys.argv[1:]

    print("\n未提供 URL，進入互動模式。")
    print("請貼上 AWS Academy 頁面 URL（多個 URL 用空格或換行分隔，輸入空行結束）:\n")
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
        # 只登入一次
        driver.get("https://awsacademy.instructure.com/login")
        print("\n  👉 請在 Chrome 中登入 AWS Academy")
        print("  👉 登入完成後回到這裡按 Enter")
        input("\n>>> ")

        # 逐一下載
        results = []
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}]")
            ok, fp = download_one(driver, url)
            results.append((url, ok, fp))

        # 彙總
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
