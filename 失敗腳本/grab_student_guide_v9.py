"""
AWS Academy Student Guide PDF Downloader v9

已知：d4 frame 有 pdfjsLib + 2 canvas + 70 pages
路徑：main -> iframe[1] -> iframe[0] -> iframe[0] -> iframe[0]
直接進去，找 PDF document 並提取。
"""

import os
import time
import json
import base64

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


def setup():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    options = Options()
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def navigate_to_d4(driver):
    """直接導航到 d4 frame: main -> [1] -> [0] -> [0] -> [0]"""
    driver.switch_to.default_content()
    path = [1, 0, 0, 0]
    for i, idx in enumerate(path):
        try:
            driver.switch_to.frame(idx)
            url = driver.execute_script("return window.location.href")
            print(f"  -> frame[{idx}]: {url[:80]}")
        except Exception as e:
            print(f"  -> frame[{idx}]: FAILED ({e})")
            return False
    return True


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v9")
    print("=" * 60)

    driver = setup()

    try:
        driver.get("https://awsacademy.instructure.com/login")
        print("\n  請在 Chrome 中登入 AWS Academy，登入完成後按 Enter")
        input("\n>>> ")

        print(f"\nNavigating to Student Guide...")
        driver.get(COURSE_URL)

        print("Waiting 35s for full load...")
        time.sleep(35)

        # 進入 d4 frame
        print("\n--- Navigating to PDF viewer frame (d4) ---")
        if not navigate_to_d4(driver):
            print("Failed to reach d4 frame")
            input("Press Enter...")
            return

        # 等一下確保 PDF 完全載入
        print("\nWaiting 5s for PDF render...")
        time.sleep(5)

        # 確認我們在對的地方
        check = driver.execute_script("""
            return {
                url: window.location.href,
                hasPdfjsLib: typeof pdfjsLib !== 'undefined',
                canvasCount: document.querySelectorAll('canvas').length,
                bodyText: document.body ? document.body.innerText.substring(0, 200) : '',
            };
        """)
        print(f"  URL: {check['url'][:80]}")
        print(f"  pdfjsLib: {check['hasPdfjsLib']}")
        print(f"  Canvas: {check['canvasCount']}")
        print(f"  Body: {check['bodyText'][:100]}")

        if not check['hasPdfjsLib']:
            print("ERROR: pdfjsLib not found in this frame!")
            input("Press Enter...")
            return

        # === 搜尋 PDF document 物件 ===
        print("\n--- Searching for PDF document object ---")

        search_result = driver.execute_script("""
            var results = [];
            
            // 1. 搜尋所有 window 屬性找 PDF document proxy
            for (var key in window) {
                try {
                    var val = window[key];
                    if (val && typeof val === 'object') {
                        // PDFDocumentProxy 有 numPages 和 getData 方法
                        if (typeof val.numPages === 'number' && typeof val.getData === 'function') {
                            results.push('FOUND_DOC:' + key + ':pages=' + val.numPages);
                        }
                        // 也找 loadingTask
                        if (val.promise && val.destroy) {
                            results.push('LOADING_TASK:' + key);
                        }
                        // 找有 pdfDocument 屬性的物件
                        if (val.pdfDocument && typeof val.pdfDocument.getData === 'function') {
                            results.push('FOUND_WRAPPER:' + key + ':pages=' + val.pdfDocument.numPages);
                        }
                    }
                } catch(e) {}
            }
            
            // 2. 搜尋常見的 PDF.js 變數名
            var names = ['pdfDoc', 'pdfDocument', 'pdf', 'doc', 'document', 'PDFDoc',
                         'pdfViewer', 'viewer', 'app', 'pdfApp', 'currentPdf',
                         '_pdfDoc', '_pdf', 'pdfProxy', 'documentProxy'];
            for (var n of names) {
                try {
                    var v = eval(n);
                    if (v && typeof v === 'object') {
                        if (typeof v.numPages === 'number') {
                            results.push('NAMED_DOC:' + n + ':pages=' + v.numPages);
                        }
                        if (v.pdfDocument) {
                            results.push('NAMED_WRAPPER:' + n);
                        }
                    }
                } catch(e) {}
            }
            
            // 3. 搜尋所有 script 標籤找 PDF URL
            var scripts = document.querySelectorAll('script');
            for (var s of scripts) {
                var text = s.textContent || '';
                // 找 getDocument 調用
                var m = text.match(/getDocument\\s*\\(\\s*['"](https?:[^'"]+)['"]/);
                if (m) results.push('GETDOC_URL:' + m[1]);
                m = text.match(/getDocument\\s*\\(\\s*\\{[^}]*url\\s*:\\s*['"](https?:[^'"]+)['"]/);
                if (m) results.push('GETDOC_URL2:' + m[1]);
                // 找任何看起來像 PDF URL 的東西
                m = text.match(/['"](https?:\\/\\/[^'"]*\\.pdf[^'"]*)['"]/i);
                if (m) results.push('PDF_URL:' + m[1]);
                // 找 data URL 或 blob
                m = text.match(/['"](blob:[^'"]+)['"]/);
                if (m) results.push('BLOB:' + m[1]);
            }
            
            // 4. 找 data attributes
            var els = document.querySelectorAll('[data-pdf-url], [data-src], [data-document-url]');
            els.forEach(function(e) {
                var url = e.getAttribute('data-pdf-url') || e.getAttribute('data-src') || e.getAttribute('data-document-url');
                if (url) results.push('DATA_ATTR:' + url);
            });
            
            // 5. 列出所有包含 pdf 的全域變數名
            var pdfVars = [];
            for (var key in window) {
                if (key.toLowerCase().includes('pdf') || key.toLowerCase().includes('viewer') || key.toLowerCase().includes('doc')) {
                    try {
                        var type = typeof window[key];
                        if (type === 'object' || type === 'function') {
                            pdfVars.push(key + ':' + type);
                        }
                    } catch(e) {}
                }
            }
            results.push('PDF_VARS:' + pdfVars.join(','));
            
            return JSON.stringify(results);
        """)

        items = json.loads(search_result)
        for item in items:
            print(f"  {item}")

        # === 嘗試提取 PDF ===
        found_doc_var = None
        pdf_url = None

        for item in items:
            if item.startswith("FOUND_DOC:"):
                found_doc_var = item.split(":")[1]
            elif item.startswith("NAMED_DOC:"):
                found_doc_var = item.split(":")[1]
            elif item.startswith("FOUND_WRAPPER:"):
                found_doc_var = item.split(":")[1] + ".pdfDocument"
            elif item.startswith("GETDOC_URL:") or item.startswith("GETDOC_URL2:") or item.startswith("PDF_URL:"):
                pdf_url = item.split(":", 1)[1]
                # Remove the prefix type
                pdf_url = ":".join(item.split(":")[1:])

        # 方法 A: 從找到的 document 物件提取
        if found_doc_var:
            print(f"\n--- Extracting from {found_doc_var} ---")
            try:
                pdf_b64 = driver.execute_script(f"""
                    var doc = {found_doc_var};
                    return doc.getData().then(function(data) {{
                        var binary = '';
                        var bytes = new Uint8Array(data);
                        var len = bytes.byteLength;
                        // 分塊轉 base64 避免 stack overflow
                        var CHUNK = 8192;
                        var chunks = [];
                        for (var i = 0; i < len; i += CHUNK) {{
                            var slice = bytes.subarray(i, Math.min(i + CHUNK, len));
                            chunks.push(String.fromCharCode.apply(null, slice));
                        }}
                        return btoa(chunks.join(''));
                    }});
                """)
                if pdf_b64:
                    data = base64.b64decode(pdf_b64)
                    fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                    with open(fp, "wb") as f:
                        f.write(data)
                    print(f"\n  SUCCESS! ({len(data)//1024} KB) -> {fp}")
                    input("\nPress Enter to close...")
                    return
            except Exception as e:
                print(f"  Extract failed: {str(e)[:200]}")

        # 方法 B: 用找到的 URL fetch
        if pdf_url:
            print(f"\n--- Fetching from URL: {pdf_url[:100]} ---")
            try:
                pdf_b64 = driver.execute_script(f"""
                    return fetch("{pdf_url}")
                        .then(function(r) {{ return r.arrayBuffer(); }})
                        .then(function(buf) {{
                            var bytes = new Uint8Array(buf);
                            var CHUNK = 8192;
                            var chunks = [];
                            for (var i = 0; i < bytes.length; i += CHUNK) {{
                                var slice = bytes.subarray(i, Math.min(i + CHUNK, bytes.length));
                                chunks.push(String.fromCharCode.apply(null, slice));
                            }}
                            return btoa(chunks.join(''));
                        }});
                """)
                if pdf_b64:
                    data = base64.b64decode(pdf_b64)
                    if data[:5] == b"%PDF-":
                        fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                        with open(fp, "wb") as f:
                            f.write(data)
                        print(f"\n  SUCCESS! ({len(data)//1024} KB) -> {fp}")
                        input("\nPress Enter to close...")
                        return
            except Exception as e:
                print(f"  Fetch failed: {str(e)[:200]}")

        # 方法 C: 暴力搜尋 - 遍歷所有物件找 getData
        print("\n--- Method C: Brute force search ---")
        try:
            brute = driver.execute_script("""
                // 搜尋閉包中的 PDF document
                // 嘗試從 pdfjsLib 的 loading task 中取得
                var allKeys = Object.keys(window);
                var found = [];
                
                for (var i = 0; i < allKeys.length; i++) {
                    var key = allKeys[i];
                    try {
                        var obj = window[key];
                        if (!obj || typeof obj !== 'object') continue;
                        
                        // 檢查物件的所有屬性
                        var props = Object.keys(obj);
                        for (var j = 0; j < props.length; j++) {
                            try {
                                var val = obj[props[j]];
                                if (val && typeof val === 'object' && typeof val.numPages === 'number') {
                                    found.push(key + '.' + props[j] + ':pages=' + val.numPages);
                                }
                                if (val && typeof val === 'object' && typeof val.getData === 'function') {
                                    found.push(key + '.' + props[j] + ':hasGetData');
                                }
                            } catch(e) {}
                        }
                    } catch(e) {}
                }
                
                return JSON.stringify(found);
            """)
            brute_items = json.loads(brute)
            for b in brute_items:
                print(f"  {b}")

            # 嘗試從找到的路徑提取
            for b in brute_items:
                if ":pages=" in b or ":hasGetData" in b:
                    path = b.split(":")[0]
                    print(f"\n  Trying: {path}.getData()...")
                    try:
                        pdf_b64 = driver.execute_script(f"""
                            var doc = {path};
                            if (typeof doc.getData !== 'function' && doc.pdfDocument) {{
                                doc = doc.pdfDocument;
                            }}
                            return doc.getData().then(function(data) {{
                                var bytes = new Uint8Array(data);
                                var CHUNK = 8192;
                                var chunks = [];
                                for (var i = 0; i < bytes.length; i += CHUNK) {{
                                    var slice = bytes.subarray(i, Math.min(i + CHUNK, bytes.length));
                                    chunks.push(String.fromCharCode.apply(null, slice));
                                }}
                                return btoa(chunks.join(''));
                            }});
                        """)
                        if pdf_b64:
                            data = base64.b64decode(pdf_b64)
                            fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                            with open(fp, "wb") as f:
                                f.write(data)
                            print(f"\n  SUCCESS! ({len(data)//1024} KB) -> {fp}")
                            input("\nPress Enter to close...")
                            return
                    except Exception as e:
                        print(f"  Failed: {str(e)[:100]}")

        except Exception as e:
            print(f"  Brute search error: {str(e)[:150]}")

        # 方法 D: Dump HTML 找線索
        print("\n--- Method D: Dump d4 frame HTML ---")
        html = driver.execute_script("return document.documentElement.outerHTML")
        fp = os.path.join(DOWNLOAD_DIR, "d4_frame.html")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Saved to: {fp}")
        print(f"  HTML length: {len(html)}")

        # 從 HTML 中搜尋 URL
        import re
        urls = re.findall(r'https?://[^\s"\'<>]+', html)
        pdf_related = [u for u in urls if any(k in u.lower() for k in ['.pdf', 'download', 'content', 'bundle', 'document'])]
        if pdf_related:
            print(f"  Interesting URLs in HTML:")
            for u in set(pdf_related):
                print(f"    {u[:120]}")

        print(f"\n  Check {fp} for full HTML")
        input("\nPress Enter to close browser...")

    except KeyboardInterrupt:
        print("\nCancelled")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
