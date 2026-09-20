"""
AWS Academy Student Guide PDF Downloader v5

核心策略：用 CDP (Chrome DevTools Protocol) 攔截所有 frame 的網路請求，
包括跨域 iframe (Vocareum) 的流量，直接擷取 PDF response body。
"""

import os
import time
import json
import base64
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

COURSE_URL = "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


def setup():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    options = Options()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    # 不要自動下載 PDF，讓它在瀏覽器內渲染，這樣我們才能攔截
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def enable_cdp_network(driver):
    """啟用 CDP Network 監聽所有 frame 的流量"""
    driver.execute_cdp_cmd("Network.enable", {
        "maxTotalBufferSize": 100 * 1024 * 1024,  # 100MB buffer
        "maxResourceBufferSize": 50 * 1024 * 1024,  # 50MB per resource
    })
    print("  CDP Network enabled")


def scan_performance_logs(driver):
    """掃描 performance log 找 PDF 相關的 request"""
    found = []
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
                    mime = resp.get("mimeType", "").lower()
                    request_id = params.get("requestId", "")
                    ct = resp.get("headers", {}).get("content-type", "").lower()
                    content_len = resp.get("headers", {}).get("content-length", "0")

                    is_pdf = "pdf" in mime or "pdf" in ct or ".pdf" in url.lower()
                    is_large = False
                    try:
                        is_large = int(content_len) > 100000
                    except (ValueError, TypeError):
                        pass

                    is_interesting = (
                        "vocareum" in url or
                        "s3.amazonaws" in url or
                        ("cloudfront" in url and "du11hjcvx0uqb" not in url)
                    )

                    if is_pdf or (is_large and is_interesting):
                        info = {
                            "requestId": request_id,
                            "url": url,
                            "mime": mime,
                            "content_type": ct,
                            "content_length": content_len,
                            "is_pdf": is_pdf,
                        }
                        found.append(info)
                        tag = "PDF!" if is_pdf else "LARGE"
                        print(f"  [{tag}] {url[:120]}")
                        print(f"       mime={mime} size={content_len} reqId={request_id}")

                elif method == "Network.requestWillBeSent":
                    url = params.get("request", {}).get("url", "")
                    if ".pdf" in url.lower() or "readfile" in url.lower():
                        print(f"  [REQ] {url[:120]}")

                elif method == "Network.loadingFinished":
                    pass  # Could track sizes here

            except Exception:
                pass
    except Exception as e:
        print(f"  Log scan error: {e}")

    return found


def try_get_response_body(driver, request_id):
    """用 CDP 取得 response body"""
    try:
        result = driver.execute_cdp_cmd("Network.getResponseBody", {
            "requestId": request_id
        })
        body = result.get("body", "")
        is_base64 = result.get("base64Encoded", False)

        if is_base64:
            data = base64.b64decode(body)
        else:
            data = body.encode("utf-8")

        return data
    except Exception as e:
        print(f"  Cannot get body for {request_id}: {e}")
        return None


def save_pdf(data, filename="student_guide.pdf"):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(data)
    print(f"  Saved ({len(data)//1024} KB): {filepath}")
    return filepath


def explore_and_click(driver, depth=0):
    """進入 iframe 找下載按鈕或 PDF 連結"""
    indent = "  " * depth
    if depth > 5:
        return

    try:
        url = driver.current_url
        title = driver.title
        print(f"{indent}[Frame] {url[:100]} | {title}")
    except Exception:
        pass

    # 找下載按鈕
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR,
            "a[download], a[href*='download'], button[aria-label*='download'], "
            "button[title*='download'], button[title*='Download'], "
            "a[aria-label*='download'], [class*='download'], "
            "a[href*='.pdf'], button[aria-label*='save'], "
            "button[title*='Save'], a[title*='Download']"
        )
        for btn in buttons:
            text = btn.text or btn.get_attribute("aria-label") or btn.get_attribute("title") or ""
            href = btn.get_attribute("href") or ""
            print(f"{indent}  BUTTON: '{text}' href={href[:80]}")
            if href and ".pdf" in href.lower():
                print(f"{indent}  >>> PDF link found!")
                return href
    except Exception:
        pass

    # 找所有 PDF 相關的 element
    try:
        embeds = driver.find_elements(By.CSS_SELECTOR, "embed[type='application/pdf'], object[type='application/pdf']")
        for e in embeds:
            src = e.get_attribute("src") or e.get_attribute("data")
            print(f"{indent}  PDF_EMBED: {src}")
            if src:
                return src
    except Exception:
        pass

    # 遞迴進入 iframe
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, f in enumerate(iframes):
            src = f.get_attribute("src") or ""
            if not src or src == "about:blank":
                continue
            print(f"{indent}  iframe[{i}]: {src[:80]}")
            try:
                driver.switch_to.frame(f)
                result = explore_and_click(driver, depth + 1)
                if result:
                    driver.switch_to.parent_frame()
                    return result
                driver.switch_to.parent_frame()
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return None


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v5")
    print("  (CDP Network Interception)")
    print("=" * 60)
    print(f"Download dir: {DOWNLOAD_DIR}\n")

    driver = setup()

    try:
        # 啟用 CDP network 監聽
        enable_cdp_network(driver)

        # 登入
        driver.get("https://awsacademy.instructure.com/login")
        print("\n" + "=" * 60)
        print("  請在 Chrome 中登入 AWS Academy")
        print("  登入完成後回到這裡按 Enter")
        print("=" * 60)
        input("\n>>> ")

        # 啟用 network interception（登入後重新啟用確保生效）
        enable_cdp_network(driver)

        # 導航
        print(f"\nNavigating to Student Guide...")
        driver.get(COURSE_URL)

        # 持續掃描 network log
        print("\nMonitoring network traffic...")
        all_found = []

        for wait_round in range(12):  # 最多等 60 秒
            time.sleep(5)
            print(f"\n--- Scan round {wait_round + 1} ---")
            found = scan_performance_logs(driver)
            all_found.extend(found)

            # 如果找到 PDF 就嘗試下載
            pdf_items = [f for f in all_found if f["is_pdf"]]
            if pdf_items:
                print(f"\n{'='*60}")
                print(f"  Found {len(pdf_items)} PDF response(s)!")
                print(f"{'='*60}")
                break

        # 嘗試用 requestId 直接取得 PDF body
        for item in all_found:
            if item.get("is_pdf") or int(item.get("content_length", 0)) > 100000:
                print(f"\nTrying to get body: {item['url'][:100]}")
                data = try_get_response_body(driver, item["requestId"])
                if data and data[:5] == b"%PDF-":
                    fp = save_pdf(data)
                    print(f"\n{'='*60}")
                    print(f"  SUCCESS! {fp}")
                    print(f"{'='*60}")
                    input("\nPress Enter to close...")
                    return
                elif data and len(data) > 50000:
                    # 可能是 PDF 但 header 不同
                    fp = save_pdf(data, "student_guide_raw.bin")
                    print(f"  Saved raw data for inspection: {fp}")

        # 如果 CDP 沒攔截到，嘗試探索 iframe 找下載按鈕
        print("\n--- Exploring iframes for download buttons ---")
        driver.switch_to.default_content()
        pdf_url = explore_and_click(driver)

        if pdf_url:
            print(f"\nFound PDF URL: {pdf_url}")
            # 用 CDP fetch 來下載
            driver.switch_to.default_content()
            driver.get(pdf_url)
            time.sleep(5)
            found2 = scan_performance_logs(driver)
            for item in found2:
                data = try_get_response_body(driver, item["requestId"])
                if data and data[:5] == b"%PDF-":
                    fp = save_pdf(data)
                    print(f"\nSUCCESS! {fp}")
                    input("\nPress Enter to close...")
                    return

        # 最後手段：列出所有攔截到的大型請求
        print(f"\n{'='*60}")
        print("  Summary of all intercepted traffic")
        print(f"{'='*60}")

        if all_found:
            for i, item in enumerate(all_found):
                print(f"  [{i}] {item['url'][:100]}")
                print(f"      mime={item['mime']} size={item['content_length']}")
        else:
            print("  No interesting traffic captured.")
            print("\n  The PDF might be rendered as page images.")
            print("  Try using Ctrl+P in Chrome to print to PDF.")

        # 嘗試 Ctrl+P 方式
        print("\n--- Attempting Page.printToPDF on all frames ---")
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, f in enumerate(iframes):
            src = f.get_attribute("src") or ""
            if not src or src == "about:blank":
                continue
            try:
                driver.switch_to.frame(f)
                # Go deeper
                inners = driver.find_elements(By.TAG_NAME, "iframe")
                for j, inf in enumerate(inners):
                    try:
                        driver.switch_to.frame(inf)
                        deeps = driver.find_elements(By.TAG_NAME, "iframe")
                        for k, df in enumerate(deeps):
                            try:
                                driver.switch_to.frame(df)
                                body_text = driver.execute_script("return document.body.innerText")
                                if body_text and len(body_text) > 500:
                                    print(f"  Found content in deep frame ({len(body_text)} chars)")
                                    r = driver.execute_cdp_cmd("Page.printToPDF", {
                                        "landscape": False,
                                        "printBackground": True,
                                        "preferCSSPageSize": True,
                                    })
                                    data = base64.b64decode(r["data"])
                                    fp = save_pdf(data, f"student_guide_frame_{i}_{j}_{k}.pdf")
                                driver.switch_to.parent_frame()
                            except Exception:
                                try:
                                    driver.switch_to.parent_frame()
                                except Exception:
                                    pass

                        body_text = driver.execute_script("return document.body.innerText")
                        if body_text and len(body_text) > 500:
                            print(f"  Found content in inner frame ({len(body_text)} chars)")
                            r = driver.execute_cdp_cmd("Page.printToPDF", {
                                "landscape": False,
                                "printBackground": True,
                                "preferCSSPageSize": True,
                            })
                            data = base64.b64decode(r["data"])
                            fp = save_pdf(data, f"student_guide_frame_{i}_{j}.pdf")

                        driver.switch_to.parent_frame()
                    except Exception:
                        try:
                            driver.switch_to.parent_frame()
                        except Exception:
                            pass
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

        print(f"\nCheck {DOWNLOAD_DIR} for any saved files.")
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
