"""
AWS Academy Student Guide PDF Downloader v8

已知結構：
  Canvas page
    -> emergingtalent iframe (ltiDispatch.html)
      -> DispatchHost.html
        -> modern.html (Rustici Player + PDF.js)

策略：進入 modern.html，等 PDF.js 完全載入後，
用 pdfDocument.getData() 直接從記憶體取得 PDF bytes。
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
    # 關閉 site isolation 讓 Selenium 能進入跨域 iframe
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def wait_and_find_pdfjs(driver, max_wait=120):
    """
    反覆探索 iframe 結構，等待 PDF.js 載入。
    找到後回傳 True（driver 已切換到 PDF.js 所在的 frame）。
    """
    start = time.time()
    attempt = 0

    while time.time() - start < max_wait:
        attempt += 1
        print(f"\n  [Attempt {attempt}] Searching for PDF.js... ({int(time.time()-start)}s elapsed)")

        driver.switch_to.default_content()

        # 遞迴搜尋所有 iframe
        found = _search_frames(driver, depth=0, max_depth=6)
        if found:
            return True

        time.sleep(5)

    return False


def _search_frames(driver, depth, max_depth):
    """遞迴搜尋 iframe，找到 PDF.js 就停"""
    if depth > max_depth:
        return False

    indent = "    " * depth

    # 檢查當前 frame 是否有 PDF.js
    try:
        result = driver.execute_script("""
            var info = {
                url: window.location.href,
                bodyLen: document.body ? document.body.innerText.length : -1,
                canvasCount: document.querySelectorAll('canvas').length,
                iframeCount: document.querySelectorAll('iframe').length,
                hasPDFJS: typeof PDFViewerApplication !== 'undefined',
                hasPDFDoc: false,
                hasWorker: typeof pdfjsLib !== 'undefined',
            };
            
            if (info.hasPDFJS && PDFViewerApplication.pdfDocument) {
                info.hasPDFDoc = true;
                info.pagesCount = PDFViewerApplication.pagesCount || 0;
                info.url_pdfjs = PDFViewerApplication.url || PDFViewerApplication.baseUrl || '';
            }
            
            // 也找 window.pdfDoc 或其他自定義變數
            if (typeof pdfDoc !== 'undefined') info.pdfDoc = true;
            if (typeof viewer !== 'undefined') info.viewer = true;
            
            // 找 canvas
            if (info.canvasCount > 0) {
                var c = document.querySelector('canvas');
                info.canvasSize = c.width + 'x' + c.height;
            }
            
            return JSON.stringify(info);
        """)
        info = json.loads(result)
        url_short = info["url"][:80] if info.get("url") else "?"

        status_parts = []
        if info.get("bodyLen", 0) > 0:
            status_parts.append(f"body={info['bodyLen']}")
        if info.get("canvasCount", 0) > 0:
            status_parts.append(f"canvas={info['canvasCount']}({info.get('canvasSize','')})")
        if info.get("hasPDFJS"):
            status_parts.append("PDFJS!")
        if info.get("hasPDFDoc"):
            status_parts.append(f"DOC({info.get('pagesCount',0)}p)")
        if info.get("hasWorker"):
            status_parts.append("pdfjsLib!")
        if info.get("iframeCount", 0) > 0:
            status_parts.append(f"iframes={info['iframeCount']}")

        status = " | ".join(status_parts) if status_parts else "empty"
        print(f"{indent}[d{depth}] {url_short} [{status}]")

        # 找到 PDF.js document!
        if info.get("hasPDFDoc"):
            print(f"{indent}  *** PDF.js Document Found! ***")
            print(f"{indent}  Pages: {info.get('pagesCount', '?')}")
            print(f"{indent}  URL: {info.get('url_pdfjs', '?')}")
            return True

        # 找到 canvas (可能是 PDF.js 但沒有 PDFViewerApplication)
        if info.get("canvasCount", 0) > 2:
            print(f"{indent}  Multiple canvases found - likely PDF.js!")
            # 嘗試找 pdfjsLib
            has_pdfjs = driver.execute_script("""
                // Check various PDF.js global objects
                var checks = [];
                if (typeof pdfjsLib !== 'undefined') checks.push('pdfjsLib');
                if (typeof PDFJS !== 'undefined') checks.push('PDFJS');
                if (typeof PDFViewerApplication !== 'undefined') checks.push('PDFViewerApplication');
                if (typeof PDFViewerApplicationOptions !== 'undefined') checks.push('PDFViewerApplicationOptions');
                
                // Check for pdf.js elements
                var viewer = document.getElementById('viewer') || 
                             document.querySelector('.pdfViewer') ||
                             document.querySelector('[data-page-number]');
                if (viewer) checks.push('viewer-element');
                
                return checks.join(',');
            """)
            print(f"{indent}  PDF.js objects: {has_pdfjs}")
            if has_pdfjs:
                return True

    except Exception as e:
        try:
            url = driver.execute_script("return window.location.href")
        except Exception:
            url = "?"
        print(f"{indent}[d{depth}] {url} [JS error: {str(e)[:60]}]")

    # 遞迴進入子 iframe
    try:
        iframe_count = driver.execute_script("return document.querySelectorAll('iframe').length")
        for i in range(iframe_count or 0):
            try:
                driver.switch_to.frame(i)
                if _search_frames(driver, depth + 1, max_depth):
                    return True
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return False


def extract_pdf_from_pdfjs(driver):
    """從 PDF.js 的記憶體中提取 PDF bytes"""
    print("\n--- Extracting PDF from PDF.js memory ---")

    # 方法 A: PDFViewerApplication.pdfDocument.getData()
    print("  Method A: PDFViewerApplication.pdfDocument.getData()")
    try:
        # getData() 回傳 Promise<Uint8Array>
        # 我們需要用 async 方式取得
        pdf_b64 = driver.execute_script("""
            return new Promise(function(resolve, reject) {
                if (typeof PDFViewerApplication === 'undefined') {
                    reject('No PDFViewerApplication');
                    return;
                }
                var doc = PDFViewerApplication.pdfDocument;
                if (!doc) {
                    reject('No pdfDocument');
                    return;
                }
                doc.getData().then(function(data) {
                    // Convert Uint8Array to base64
                    var binary = '';
                    var len = data.byteLength;
                    for (var i = 0; i < len; i++) {
                        binary += String.fromCharCode(data[i]);
                    }
                    resolve(btoa(binary));
                }).catch(function(err) {
                    reject(err.toString());
                });
            });
        """)

        if pdf_b64:
            data = base64.b64decode(pdf_b64)
            if data[:5] == b"%PDF-":
                fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                with open(fp, "wb") as f:
                    f.write(data)
                print(f"  SUCCESS! Saved ({len(data)//1024} KB): {fp}")
                return fp
            else:
                print(f"  Got data ({len(data)} bytes) but not PDF header")

    except Exception as e:
        err = str(e)
        print(f"  Method A failed: {err[:150]}")

    # 方法 B: 分塊提取（大 PDF 可能需要）
    print("  Method B: Chunked extraction")
    try:
        total_size = driver.execute_script("""
            if (typeof PDFViewerApplication !== 'undefined' && PDFViewerApplication.pdfDocument) {
                return PDFViewerApplication.pdfDocument.getData().then(function(d) { return d.byteLength; });
            }
            return 0;
        """)
        print(f"  Total PDF size: {total_size} bytes")

        if total_size and total_size > 0:
            chunk_size = 500000  # 500KB per chunk
            chunks = []
            for offset in range(0, total_size, chunk_size):
                chunk_b64 = driver.execute_script(f"""
                    return PDFViewerApplication.pdfDocument.getData().then(function(data) {{
                        var slice = data.slice({offset}, {min(offset + chunk_size, total_size)});
                        var binary = '';
                        for (var i = 0; i < slice.byteLength; i++) {{
                            binary += String.fromCharCode(slice[i]);
                        }}
                        return btoa(binary);
                    }});
                """)
                if chunk_b64:
                    chunks.append(base64.b64decode(chunk_b64))
                    print(f"    Chunk {offset//chunk_size + 1}: {len(chunks[-1])} bytes")

            if chunks:
                data = b"".join(chunks)
                fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                with open(fp, "wb") as f:
                    f.write(data)
                print(f"  SUCCESS! Saved ({len(data)//1024} KB): {fp}")
                return fp

    except Exception as e:
        print(f"  Method B failed: {str(e)[:150]}")

    # 方法 C: 取得 PDF URL 然後用 fetch 下載
    print("  Method C: Get URL and fetch")
    try:
        pdf_url = driver.execute_script("""
            if (typeof PDFViewerApplication !== 'undefined') {
                return PDFViewerApplication.url || PDFViewerApplication.baseUrl || '';
            }
            // 也試試 pdfjsLib
            if (typeof pdfjsLib !== 'undefined') {
                return 'pdfjsLib found but no URL';
            }
            // 搜尋所有 script 和 data attribute
            var scripts = document.querySelectorAll('script');
            for (var s of scripts) {
                var m = (s.textContent || '').match(/['"](https?:\/\/[^'"]+\.pdf[^'"]*)['"]/i);
                if (m) return m[1];
                m = (s.textContent || '').match(/documentUrl\s*[=:]\s*['"](https?:\/\/[^'"]+)['"]/i);
                if (m) return m[1];
                m = (s.textContent || '').match(/file\s*[=:]\s*['"](https?:\/\/[^'"]+)['"]/i);
                if (m) return m[1];
            }
            return 'NOT_FOUND';
        """)
        print(f"  PDF URL: {pdf_url}")

        if pdf_url and pdf_url.startswith("http"):
            # 用 browser 的 fetch 下載（帶 cookies）
            fetch_b64 = driver.execute_script(f"""
                return fetch("{pdf_url}")
                    .then(r => r.arrayBuffer())
                    .then(buf => {{
                        var bytes = new Uint8Array(buf);
                        var binary = '';
                        for (var i = 0; i < bytes.length; i++) {{
                            binary += String.fromCharCode(bytes[i]);
                        }}
                        return btoa(binary);
                    }});
            """)
            if fetch_b64:
                data = base64.b64decode(fetch_b64)
                if data[:5] == b"%PDF-":
                    fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                    with open(fp, "wb") as f:
                        f.write(data)
                    print(f"  SUCCESS! Saved ({len(data)//1024} KB): {fp}")
                    return fp

    except Exception as e:
        print(f"  Method C failed: {str(e)[:150]}")

    # 方法 D: 用 Page.printToPDF 在當前 frame
    print("  Method D: Print current frame to PDF")
    try:
        result = driver.execute_cdp_cmd("Page.printToPDF", {
            "landscape": False,
            "printBackground": True,
            "preferCSSPageSize": True,
        })
        data = base64.b64decode(result["data"])
        if len(data) > 5000:
            fp = os.path.join(DOWNLOAD_DIR, "student_guide_print.pdf")
            with open(fp, "wb") as f:
                f.write(data)
            print(f"  Saved print version ({len(data)//1024} KB): {fp}")
            return fp
    except Exception as e:
        print(f"  Method D failed: {str(e)[:60]}")

    return None


def dump_frame_html(driver):
    """Dump 當前 frame 的 HTML 結構用於 debug"""
    try:
        html = driver.execute_script("""
            return document.documentElement.outerHTML.substring(0, 5000);
        """)
        fp = os.path.join(DOWNLOAD_DIR, "debug_frame.html")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Dumped frame HTML to: {fp}")

        # 也列出所有 JS 全域變數
        globals_info = driver.execute_script("""
            var interesting = [];
            var skip = ['chrome','cdc_adoQpoasnfa76pfcZLmcfl_'];
            for (var key in window) {
                if (skip.some(s => key.startsWith(s))) continue;
                try {
                    var val = window[key];
                    var type = typeof val;
                    if (type === 'function' || type === 'object') {
                        if (key.toLowerCase().includes('pdf') || 
                            key.toLowerCase().includes('viewer') ||
                            key.toLowerCase().includes('document') ||
                            key.toLowerCase().includes('player')) {
                            interesting.push(key + ':' + type);
                        }
                    }
                } catch(e) {}
            }
            return interesting.join(', ');
        """)
        print(f"  Interesting globals: {globals_info}")

    except Exception as e:
        print(f"  Dump failed: {e}")


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v8")
    print("  (Direct PDF.js memory extraction)")
    print("=" * 60)

    driver = setup()

    try:
        driver.get("https://awsacademy.instructure.com/login")
        print("\n  請在 Chrome 中登入 AWS Academy，登入完成後按 Enter")
        input("\n>>> ")

        print(f"\nNavigating to Student Guide...")
        driver.get(COURSE_URL)

        print("Waiting for page initial load (10s)...")
        time.sleep(10)

        # 搜尋 PDF.js（最多等 120 秒）
        print(f"\n{'='*60}")
        print("Searching for PDF.js in iframe tree...")
        print("(Will poll every 5s for up to 2 minutes)")
        print("=" * 60)

        found = wait_and_find_pdfjs(driver, max_wait=120)

        if found:
            print(f"\n{'='*60}")
            print("PDF.js found! Attempting extraction...")
            print("=" * 60)

            # 先 dump 一下 frame 結構
            dump_frame_html(driver)

            # 提取 PDF
            fp = extract_pdf_from_pdfjs(driver)

            if fp:
                print(f"\n{'='*60}")
                print(f"  PDF saved to: {fp}")
                print(f"{'='*60}")
            else:
                print(f"\n  Extraction failed. Check debug_frame.html in {DOWNLOAD_DIR}")
        else:
            print(f"\n{'='*60}")
            print("PDF.js not found after 2 minutes.")
            print("Dumping all frame info for debug...")
            print("=" * 60)

            # Dump 所有 frame 資訊
            driver.switch_to.default_content()
            targets = driver.execute_cdp_cmd("Target.getTargets", {})
            for t in targets.get("targetInfos", []):
                print(f"  [{t['type']}] {t['url'][:120]}")

            # 嘗試進入每個 iframe 並 dump
            driver.switch_to.default_content()
            _dump_all_frames(driver, 0)

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


def _dump_all_frames(driver, depth):
    if depth > 6:
        return
    indent = "  " * depth
    try:
        url = driver.execute_script("return window.location.href")
        body = driver.execute_script(
            "return document.body ? document.body.innerText.substring(0, 300) : '(no body)'")
        html_len = driver.execute_script(
            "return document.documentElement ? document.documentElement.innerHTML.length : 0")
        print(f"{indent}[d{depth}] {url[:100]}")
        print(f"{indent}  html={html_len} body='{body[:100]}'")
    except Exception as e:
        print(f"{indent}[d{depth}] error: {e}")
        return

    try:
        count = driver.execute_script("return document.querySelectorAll('iframe').length")
        for i in range(count or 0):
            try:
                driver.switch_to.frame(i)
                _dump_all_frames(driver, depth + 1)
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
