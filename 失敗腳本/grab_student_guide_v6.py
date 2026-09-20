"""
AWS Academy Student Guide PDF Downloader v6

改用 CDP Target API 來發現所有 frame（包括跨域 OOPIF），
直接在 frame context 中執行 JS 來找 PDF。

並且不跳過 about:blank iframe，因為 LTI 可能透過 JS 把 iframe 導航到其他 URL。
"""

import os
import time
import json
import base64
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


def setup():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    options = Options()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def get_frame_tree(driver):
    """用 CDP 取得完整的 frame tree"""
    try:
        result = driver.execute_cdp_cmd("Page.getFrameTree", {})
        return result
    except Exception as e:
        print(f"  getFrameTree error: {e}")
        return None


def print_frame_tree(tree, indent=0):
    """列印 frame tree"""
    prefix = "  " * indent
    frame = tree.get("frame", {})
    url = frame.get("url", "?")
    frame_id = frame.get("id", "?")
    name = frame.get("name", "")
    security = frame.get("securityOrigin", "")
    print(f"{prefix}[{frame_id}] {url[:100]}")
    if name:
        print(f"{prefix}  name={name} origin={security}")

    for child in tree.get("childFrames", []):
        print_frame_tree(child, indent + 1)


def collect_frame_urls(tree, urls=None):
    """收集所有 frame 的 URL 和 ID"""
    if urls is None:
        urls = []
    frame = tree.get("frame", {})
    urls.append({
        "id": frame.get("id"),
        "url": frame.get("url", ""),
        "name": frame.get("name", ""),
        "origin": frame.get("securityOrigin", ""),
    })
    for child in tree.get("childFrames", []):
        collect_frame_urls(child, urls)
    return urls


def get_all_targets(driver):
    """用 CDP 取得所有 target（包括 OOPIF）"""
    try:
        result = driver.execute_cdp_cmd("Target.getTargets", {})
        return result.get("targetInfos", [])
    except Exception as e:
        print(f"  getTargets error: {e}")
        return []


def try_runtime_evaluate_in_frame(driver, frame_id, expression):
    """在指定 frame 中執行 JS"""
    try:
        # 先建立 execution context
        result = driver.execute_cdp_cmd("Page.createIsolatedWorld", {
            "frameId": frame_id,
            "worldName": "pdf_finder",
        })
        context_id = result.get("executionContextId")

        if context_id:
            eval_result = driver.execute_cdp_cmd("Runtime.evaluate", {
                "expression": expression,
                "contextId": context_id,
                "returnByValue": True,
            })
            return eval_result.get("result", {}).get("value")
    except Exception as e:
        print(f"    Runtime.evaluate error: {e}")
    return None


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v6")
    print("  (CDP Target + Frame Tree)")
    print("=" * 60)
    print(f"Download dir: {DOWNLOAD_DIR}\n")

    driver = setup()

    try:
        driver.execute_cdp_cmd("Network.enable", {})

        driver.get("https://awsacademy.instructure.com/login")
        print("\n  請在 Chrome 中登入 AWS Academy")
        print("  登入完成後按 Enter")
        input("\n>>> ")

        driver.execute_cdp_cmd("Network.enable", {})

        print(f"\nNavigating to Student Guide...")
        driver.get(COURSE_URL)

        print("Waiting 30s for full page + LTI load...")
        time.sleep(30)

        # === 1. Frame Tree ===
        print(f"\n{'='*60}")
        print("1. Frame Tree (CDP)")
        print("=" * 60)
        tree = get_frame_tree(driver)
        if tree:
            print_frame_tree(tree)
            frames = collect_frame_urls(tree)
            print(f"\nTotal frames: {len(frames)}")
        else:
            frames = []

        # === 2. All Targets (OOPIF) ===
        print(f"\n{'='*60}")
        print("2. All Targets (includes OOPIF)")
        print("=" * 60)
        targets = get_all_targets(driver)
        for t in targets:
            ttype = t.get("type", "?")
            turl = t.get("url", "?")
            ttitle = t.get("title", "")
            tid = t.get("targetId", "")
            print(f"  [{ttype}] {turl[:100]}")
            if ttitle:
                print(f"    title={ttitle} id={tid}")

        # === 3. 在每個 frame 中搜尋 PDF ===
        print(f"\n{'='*60}")
        print("3. Searching for PDF in each frame")
        print("=" * 60)

        search_js = """
        (function() {
            var results = [];
            var html = document.documentElement ? document.documentElement.innerHTML : '';
            
            // PDF URLs
            var m = html.match(/https?:\\/\\/[^\\s"'<>]+\\.pdf[^\\s"'<>]*/gi);
            if(m) m.forEach(function(x){ results.push('PDF:'+x); });
            
            // S3
            m = html.match(/https?:\\/\\/[^\\s"'<>]*s3[^\\s"'<>]*amazonaws[^\\s"'<>]*/gi);
            if(m) m.forEach(function(x){ results.push('S3:'+x); });
            
            // Download links
            m = html.match(/https?:\\/\\/[^\\s"'<>]*\\/download[^\\s"'<>]*/gi);
            if(m) m.forEach(function(x){ results.push('DL:'+x); });
            
            // Vocareum
            m = html.match(/https?:\\/\\/[^\\s"'<>]*vocareum[^\\s"'<>]*/gi);
            if(m) m.forEach(function(x){ results.push('VOC:'+x); });
            
            // Embeds
            document.querySelectorAll('embed,object,video,source').forEach(function(e){
                var s = e.src || e.data || e.getAttribute('src');
                if(s) results.push('EMBED:'+s);
            });
            
            // All links
            document.querySelectorAll('a[href]').forEach(function(a){
                results.push('LINK:'+a.href);
            });
            
            // Page info
            results.push('URL:'+window.location.href);
            results.push('TITLE:'+document.title);
            results.push('BODYLEN:'+((document.body&&document.body.innerText)||'').length);
            
            return JSON.stringify([...new Set(results)]);
        })()
        """

        all_pdf_urls = []

        for frame_info in frames:
            fid = frame_info["id"]
            furl = frame_info["url"]
            print(f"\n  Frame: {furl[:80]}")

            result = try_runtime_evaluate_in_frame(driver, fid, search_js)
            if result:
                try:
                    items = json.loads(result)
                    for item in items:
                        if item.startswith("URL:") or item.startswith("TITLE:") or item.startswith("BODYLEN:"):
                            print(f"    {item}")
                        elif not item.startswith("LINK:") or ".pdf" in item.lower() or "download" in item.lower():
                            print(f"    {item}")
                            if any(k in item.lower() for k in [".pdf", "s3.", "download", "readfile"]):
                                all_pdf_urls.append(item)
                except json.JSONDecodeError:
                    print(f"    Raw: {result[:200]}")

        # === 4. Performance log scan ===
        print(f"\n{'='*60}")
        print("4. Performance log scan")
        print("=" * 60)

        try:
            logs = driver.get_log("performance")
            interesting = []
            for entry in logs:
                try:
                    msg = json.loads(entry["message"])["message"]
                    if msg.get("method") == "Network.responseReceived":
                        r = msg["params"]["response"]
                        url = r.get("url", "")
                        mime = r.get("mimeType", "")
                        size = r.get("headers", {}).get("content-length", "?")
                        
                        # 過濾掉不重要的
                        dominated_by_canvas_cdn = "du11hjcvx0uqb" in url
                        is_js_css = url.endswith(".js") or url.endswith(".css") or ".woff" in url
                        
                        if not dominated_by_canvas_cdn and not is_js_css:
                            interesting.append({"url": url, "mime": mime, "size": size, 
                                              "reqId": msg["params"].get("requestId", "")})
                except Exception:
                    pass
            
            print(f"  {len(interesting)} interesting responses:")
            for item in interesting:
                print(f"    [{item['mime']}] ({item['size']}) {item['url'][:100]}")
                if "pdf" in item["mime"].lower() or ".pdf" in item["url"].lower():
                    print(f"    ^^^ PDF FOUND! Attempting download...")
                    try:
                        body = driver.execute_cdp_cmd("Network.getResponseBody", 
                                                      {"requestId": item["reqId"]})
                        data = base64.b64decode(body["body"]) if body.get("base64Encoded") else body["body"].encode()
                        if data[:5] == b"%PDF-":
                            fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
                            with open(fp, "wb") as f:
                                f.write(data)
                            print(f"    SAVED: {fp}")
                    except Exception as e:
                        print(f"    Body fetch failed: {e}")

        except Exception as e:
            print(f"  Log error: {e}")

        # === 5. 嘗試 Selenium 進入所有 iframe（包括 about:blank） ===
        print(f"\n{'='*60}")
        print("5. Selenium iframe walk (including about:blank)")
        print("=" * 60)

        driver.switch_to.default_content()
        all_iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"  Found {len(all_iframes)} iframes")

        for i, iframe in enumerate(all_iframes):
            src = iframe.get_attribute("src") or "(none)"
            print(f"\n  iframe[{i}] src={src[:80]}")
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(i)  # 用 index 切換
                actual_url = driver.execute_script("return window.location.href")
                body_len = driver.execute_script("return document.body ? document.body.innerText.length : 0")
                print(f"    actual URL: {actual_url}")
                print(f"    body length: {body_len}")

                if body_len > 100:
                    body_text = driver.execute_script("return document.body.innerText.substring(0, 500)")
                    print(f"    body preview: {body_text[:200]}")

                # 找子 iframe
                sub_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                for j, sf in enumerate(sub_iframes):
                    ssrc = sf.get_attribute("src") or "(none)"
                    print(f"    sub iframe[{j}] src={ssrc[:80]}")
                    try:
                        driver.switch_to.frame(j)
                        sub_url = driver.execute_script("return window.location.href")
                        sub_body = driver.execute_script("return document.body ? document.body.innerText.length : 0")
                        print(f"      actual URL: {sub_url}")
                        print(f"      body length: {sub_body}")
                        if sub_body > 100:
                            txt = driver.execute_script("return document.body.innerText.substring(0, 500)")
                            print(f"      preview: {txt[:200]}")
                        driver.switch_to.parent_frame()
                    except Exception as e:
                        print(f"      (cannot enter: {e})")
                        try:
                            driver.switch_to.parent_frame()
                        except Exception:
                            pass

            except Exception as e:
                print(f"    (cannot enter: {e})")

        # Summary
        print(f"\n{'='*60}")
        print("  DONE - check output above for clues")
        print(f"{'='*60}")

        if all_pdf_urls:
            print(f"\n  PDF candidates found:")
            for u in all_pdf_urls:
                print(f"    {u}")

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
