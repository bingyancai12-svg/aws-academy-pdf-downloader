"""
AWS Academy Student Guide PDF Downloader v7

已知：PDF 由 emergingtalent.contentcontroller.com 透過 PDF.js 渲染。
策略：attach 到該 iframe 的 target，用 CDP 攔截 PDF.js 的網路請求，
或直接從 PDF.js 的 PDFViewerApplication 取得 PDF URL。
"""

import os
import time
import json
import base64
import urllib.request
import re
from urllib.parse import unquote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


def setup():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    options = Options()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    # 開啟 auto-attach 讓 CDP 能看到 OOPIF
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def find_targets(driver, url_contains):
    """找到包含特定 URL 的 target"""
    targets = driver.execute_cdp_cmd("Target.getTargets", {})
    matching = []
    for t in targets.get("targetInfos", []):
        if url_contains.lower() in t.get("url", "").lower():
            matching.append(t)
    return matching


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v7")
    print("  (Target: emergingtalent.contentcontroller.com)")
    print("=" * 60)

    driver = setup()

    try:
        driver.execute_cdp_cmd("Network.enable", {})

        driver.get("https://awsacademy.instructure.com/login")
        print("\n  請在 Chrome 中登入 AWS Academy，登入完成後按 Enter")
        input("\n>>> ")

        driver.execute_cdp_cmd("Network.enable", {})

        print(f"\nNavigating to Student Guide...")
        driver.get(COURSE_URL)

        print("Waiting 30s for LTI + PDF.js load...")
        time.sleep(30)

        # === 找到 emergingtalent iframe ===
        print("\n--- Finding emergingtalent targets ---")
        targets = find_targets(driver, "emergingtalent")
        worker_targets = find_targets(driver, "pdf.worker")

        for t in targets:
            print(f"  [{t['type']}] {t['url'][:120]}")
            print(f"    id={t['targetId']}")
        for t in worker_targets:
            print(f"  [worker] {t['url'][:120]}")
            print(f"    id={t['targetId']}")

        # === Attach 到 iframe target ===
        iframe_target = None
        for t in targets:
            if t["type"] == "iframe":
                iframe_target = t
                break

        if not iframe_target:
            print("ERROR: emergingtalent iframe not found")
            input("Press Enter...")
            return

        print(f"\n--- Attaching to iframe target ---")
        target_id = iframe_target["targetId"]

        try:
            session = driver.execute_cdp_cmd("Target.attachToTarget", {
                "targetId": target_id,
                "flatten": True,
            })
            session_id = session.get("sessionId")
            print(f"  Attached! sessionId={session_id}")
        except Exception as e:
            print(f"  Attach error: {e}")
            session_id = None

        # === 方法 1: 解析 iframe URL 中的 contentUrl ===
        print(f"\n--- Method 1: Extract contentUrl from iframe URL ---")
        iframe_url = iframe_target["url"]

        # 從 URL 中提取 config 參數
        config_match = re.search(r'config=(%7B.+?)(?:&|$)', iframe_url)
        if config_match:
            config_encoded = config_match.group(1)
            config_str = unquote(config_encoded)
            print(f"  Config: {config_str[:200]}")

            try:
                config = json.loads(config_str)
                content_url = config.get("contentUrl", "")
                print(f"  contentUrl: {content_url[:150]}")

                if content_url:
                    # 嘗試直接存取 contentUrl
                    print(f"\n  Trying to access contentUrl...")
                    cookies = driver.get_cookies()
                    ck = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

                    req = urllib.request.Request(content_url)
                    req.add_header("Cookie", ck)
                    req.add_header("User-Agent", driver.execute_script("return navigator.userAgent"))
                    try:
                        resp = urllib.request.urlopen(req, timeout=30)
                        data = resp.read()
                        ct = resp.headers.get("Content-Type", "")
                        print(f"  Response: {ct} ({len(data)} bytes)")
                        if data[:5] == b"%PDF-":
                            fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                            with open(fp, "wb") as f:
                                f.write(data)
                            print(f"\n  SUCCESS! Saved: {fp}")
                            input("\nPress Enter to close...")
                            return
                        elif b"<html" in data[:500].lower():
                            print(f"  HTML response (first 300 chars):")
                            print(f"  {data[:300].decode('utf-8', errors='replace')}")
                            # 可能需要從 HTML 中提取 PDF URL
                            pdf_urls = re.findall(rb'https?://[^\s"\'<>]+\.pdf[^\s"\'<>]*', data)
                            for pu in pdf_urls:
                                print(f"  Found PDF URL in response: {pu.decode()}")
                    except Exception as e:
                        print(f"  Access failed: {e}")

            except json.JSONDecodeError as e:
                print(f"  JSON parse error: {e}")

        # === 方法 2: 在 iframe 中用 Selenium 找 PDF.js viewer ===
        print(f"\n--- Method 2: Navigate into iframe via Selenium ---")
        driver.switch_to.default_content()

        all_iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(len(all_iframes)):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(i)
                url = driver.execute_script("return window.location.href")
                if "emergingtalent" in url or "contentcontroller" in url:
                    print(f"  Found emergingtalent iframe at index {i}")
                    print(f"  URL: {url[:120]}")

                    # 找子 iframe
                    subs = driver.find_elements(By.TAG_NAME, "iframe")
                    print(f"  Sub-iframes: {len(subs)}")
                    for j in range(len(subs)):
                        try:
                            driver.switch_to.frame(j)
                            sub_url = driver.execute_script("return window.location.href")
                            body_len = driver.execute_script(
                                "return document.body ? document.body.innerText.length : 0")
                            print(f"    sub[{j}] URL: {sub_url[:100]} body={body_len}")

                            # 找 PDF.js 的 document URL
                            pdf_url = driver.execute_script("""
                                // PDF.js stores the URL in various places
                                if (typeof PDFViewerApplication !== 'undefined') {
                                    return 'PDFJS:' + (PDFViewerApplication.url || 
                                           PDFViewerApplication.baseUrl || '');
                                }
                                // Check for pdf.js viewer iframe
                                var viewer = document.querySelector('#viewer, #viewerContainer, .pdfViewer');
                                if (viewer) return 'VIEWER_FOUND';
                                
                                // Check for canvas elements (PDF.js renders to canvas)
                                var canvases = document.querySelectorAll('canvas');
                                if (canvases.length > 0) return 'CANVAS:' + canvases.length;
                                
                                // Check for embed/object
                                var embed = document.querySelector('embed[type="application/pdf"]');
                                if (embed) return 'EMBED:' + embed.src;
                                
                                // Look for PDF URL in script tags or data attributes
                                var html = document.documentElement.innerHTML;
                                var m = html.match(/["'](https?:\/\/[^"']+\.pdf[^"']*)/i);
                                if (m) return 'REGEX:' + m[1];
                                
                                // Look for blob URLs
                                m = html.match(/(blob:https?:\/\/[^"'\s]+)/i);
                                if (m) return 'BLOB:' + m[1];

                                return 'NOTHING_FOUND (body=' + document.body.innerText.substring(0, 200) + ')';
                            """)
                            print(f"    PDF.js check: {pdf_url}")

                            # 更深的 iframe
                            deeps = driver.find_elements(By.TAG_NAME, "iframe")
                            print(f"    Deep iframes: {len(deeps)}")
                            for k in range(len(deeps)):
                                try:
                                    driver.switch_to.frame(k)
                                    deep_url = driver.execute_script("return window.location.href")
                                    deep_body = driver.execute_script(
                                        "return document.body ? document.body.innerText.length : 0")
                                    print(f"      deep[{k}] URL: {deep_url[:100]} body={deep_body}")

                                    deep_pdf = driver.execute_script("""
                                        if (typeof PDFViewerApplication !== 'undefined') {
                                            return JSON.stringify({
                                                url: PDFViewerApplication.url || '',
                                                baseUrl: PDFViewerApplication.baseUrl || '',
                                                pagesCount: PDFViewerApplication.pagesCount || 0,
                                            });
                                        }
                                        var canvases = document.querySelectorAll('canvas');
                                        if (canvases.length > 0) return 'CANVAS:' + canvases.length;
                                        
                                        var html = document.documentElement.innerHTML;
                                        var m = html.match(/["'](https?:\/\/[^"']+\.pdf[^"']*)/i);
                                        if (m) return 'REGEX:' + m[1];
                                        
                                        m = html.match(/(blob:https?:\/\/[^"'\s]+)/i);
                                        if (m) return 'BLOB:' + m[1];
                                        
                                        // Check all script content for PDF URL
                                        var scripts = document.querySelectorAll('script');
                                        for (var s of scripts) {
                                            var t = s.textContent || '';
                                            m = t.match(/["'](https?:\/\/[^"']+\.pdf[^"']*)/i);
                                            if (m) return 'SCRIPT:' + m[1];
                                            m = t.match(/documentUrl['":\s]+(["'])(https?:\/\/[^"']+)\1/i);
                                            if (m) return 'DOCURL:' + m[2];
                                        }
                                        
                                        return 'NOTHING (body=' + (document.body ? document.body.innerText.substring(0, 200) : 'null') + ')';
                                    """)
                                    print(f"      PDF check: {deep_pdf}")

                                    if deep_pdf and deep_pdf.startswith("{"):
                                        info = json.loads(deep_pdf)
                                        if info.get("url"):
                                            print(f"\n      PDF URL FOUND: {info['url']}")

                                    driver.switch_to.parent_frame()
                                except Exception as e:
                                    print(f"      deep[{k}] error: {e}")
                                    try:
                                        driver.switch_to.parent_frame()
                                    except Exception:
                                        pass

                            driver.switch_to.parent_frame()
                        except Exception as e:
                            print(f"    sub[{j}] error: {e}")
                            try:
                                driver.switch_to.parent_frame()
                            except Exception:
                                pass
                    break
            except Exception as e:
                pass

        # === 方法 3: 掃描 performance log 找 PDF 請求 ===
        print(f"\n--- Method 3: Deep performance log scan ---")
        try:
            logs = driver.get_log("performance")
            for entry in logs:
                try:
                    msg = json.loads(entry["message"])["message"]
                    method = msg.get("method", "")
                    params = msg.get("params", {})

                    if method == "Network.requestWillBeSent":
                        url = params.get("request", {}).get("url", "")
                        if "emergingtalent" in url or "contentcontroller" in url:
                            req_type = params.get("type", "?")
                            print(f"  [REQ] ({req_type}) {url[:150]}")

                    elif method == "Network.responseReceived":
                        resp = params.get("response", {})
                        url = resp.get("url", "")
                        if "emergingtalent" in url or "contentcontroller" in url:
                            mime = resp.get("mimeType", "")
                            size = resp.get("headers", {}).get("content-length", "?")
                            req_id = params.get("requestId", "")
                            print(f"  [RESP] ({mime}) ({size}B) {url[:150]}")

                            if "pdf" in mime.lower() or ".pdf" in url.lower():
                                print(f"  *** PDF RESPONSE! Fetching body...")
                                try:
                                    body = driver.execute_cdp_cmd(
                                        "Network.getResponseBody", {"requestId": req_id})
                                    data = (base64.b64decode(body["body"])
                                            if body.get("base64Encoded")
                                            else body["body"].encode())
                                    if data[:5] == b"%PDF-":
                                        fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                                        with open(fp, "wb") as f:
                                            f.write(data)
                                        print(f"  SAVED: {fp} ({len(data)//1024} KB)")
                                        input("\nPress Enter to close...")
                                        return
                                except Exception as e:
                                    print(f"  Body fetch: {e}")

                except Exception:
                    pass
        except Exception as e:
            print(f"  Log error: {e}")

        # === 方法 4: 直接用 CDP Fetch 攔截 ===
        print(f"\n--- Method 4: Reload with Fetch interception ---")
        try:
            # Enable Fetch domain to intercept PDF requests
            driver.execute_cdp_cmd("Fetch.enable", {
                "patterns": [
                    {"urlPattern": "*emergingtalent*", "requestStage": "Response"},
                    {"urlPattern": "*.pdf*", "requestStage": "Response"},
                    {"urlPattern": "*contentcontroller*", "requestStage": "Response"},
                ]
            })
            print("  Fetch interception enabled, reloading page...")
        except Exception as e:
            print(f"  Fetch enable error: {e}")

        # 重新載入頁面觸發 PDF 重新下載
        driver.refresh()
        print("  Waiting 30s for reload...")
        time.sleep(30)

        # 再次掃描 performance log
        print("\n  Scanning logs after reload...")
        try:
            logs = driver.get_log("performance")
            for entry in logs:
                try:
                    msg = json.loads(entry["message"])["message"]
                    method = msg.get("method", "")
                    params = msg.get("params", {})

                    if method == "Network.responseReceived":
                        resp = params.get("response", {})
                        url = resp.get("url", "")
                        mime = resp.get("mimeType", "")
                        if ("emergingtalent" in url or "contentcontroller" in url
                                or "pdf" in mime.lower() or ".pdf" in url.lower()):
                            size = resp.get("headers", {}).get("content-length", "?")
                            req_id = params.get("requestId", "")
                            print(f"    [{mime}] ({size}B) {url[:150]}")

                            if "pdf" in mime.lower() or ".pdf" in url.lower():
                                try:
                                    body = driver.execute_cdp_cmd(
                                        "Network.getResponseBody", {"requestId": req_id})
                                    data = (base64.b64decode(body["body"])
                                            if body.get("base64Encoded")
                                            else body["body"].encode())
                                    if len(data) > 10000:
                                        fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                                        with open(fp, "wb") as f:
                                            f.write(data)
                                        print(f"    SAVED: {fp} ({len(data)//1024} KB)")
                                        input("\nPress Enter...")
                                        return
                                except Exception as e:
                                    print(f"    Body: {e}")

                    elif method == "Fetch.requestPaused":
                        url = params.get("request", {}).get("url", "")
                        req_id = params.get("requestId", "")
                        print(f"    [PAUSED] {url[:150]}")
                        # Continue the request
                        try:
                            driver.execute_cdp_cmd("Fetch.continueRequest",
                                                   {"requestId": req_id})
                        except Exception:
                            pass

                except Exception:
                    pass
        except Exception as e:
            print(f"  Error: {e}")

        print(f"\n{'='*60}")
        print("  Scan complete. Check output above.")
        print(f"{'='*60}")
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
