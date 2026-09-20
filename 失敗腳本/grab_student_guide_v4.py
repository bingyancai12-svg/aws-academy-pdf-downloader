"""
AWS Academy Student Guide PDF Downloader v4
直接用 Selenium 開新 Chrome，不需要 remote debugging。
"""

import os
import time
import json
import re
import base64
import urllib.request
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


def explore_iframes(driver, depth=0):
    indent = "  " * depth
    results = []
    if depth > 5:
        return results

    try:
        url = driver.current_url
        print(f"{indent}[Frame d={depth}] {url[:120]}")
    except Exception:
        print(f"{indent}[Frame d={depth}] (no url)")

    try:
        js = driver.execute_script(r"""
            var r = [];
            var h = document.documentElement.innerHTML;
            var ps = [
                [/https?:\/\/[^\s"'<>]+\.pdf[^\s"'<>]*/gi, 'PDF'],
                [/https?:\/\/[^\s"'<>]*s3[^\s"'<>]*amazonaws[^\s"'<>]*/gi, 'S3'],
                [/https?:\/\/[^\s"'<>]*\/download[^\s"'<>]*/gi, 'DL'],
                [/https?:\/\/[^\s"'<>]*readfile[^\s"'<>]*/gi, 'RF'],
                [/https?:\/\/[^\s"'<>]*vocareum[^\s"'<>]*/gi, 'VOC'],
            ];
            ps.forEach(function(p){
                var m = h.match(p[0]);
                if(m) m.forEach(function(x){ r.push(p[1]+': '+x); });
            });
            var cf = h.match(/https?:\/\/[^\s"'<>]*cloudfront[^\s"'<>]*/gi);
            if(cf) cf.forEach(function(x){
                if(x.indexOf('du11hjcvx0uqb')===-1) r.push('CF: '+x);
            });
            var fi = h.match(/\/files\/\d+/g);
            if(fi) fi.forEach(function(x){ r.push('FILE: '+x); });
            document.querySelectorAll('embed,object').forEach(function(e){
                var s=e.src||e.data; if(s) r.push('EMBED: '+s);
            });
            document.querySelectorAll('a').forEach(function(a){
                if(a.href&&(a.href.indexOf('.pdf')!==-1||a.href.indexOf('download')!==-1))
                    r.push('LINK: '+a.href);
            });
            return [...new Set(r)];
        """)
        if js:
            for x in js:
                print(f"{indent}  >> {x}")
                results.append(x)
    except Exception as e:
        print(f"{indent}  (js err: {e})")

    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, f in enumerate(iframes):
            src = f.get_attribute("src") or ""
            if not src or src == "about:blank":
                continue
            print(f"{indent}  -> iframe[{i}]: {src[:100]}")
            try:
                driver.switch_to.frame(f)
                results.extend(explore_iframes(driver, depth + 1))
                driver.switch_to.parent_frame()
            except Exception as e:
                print(f"{indent}     (skip: {e})")
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
    except Exception:
        pass

    return results


def try_download(driver, raw_url):
    url = raw_url
    for p in ["PDF: ", "S3: ", "DL: ", "RF: ", "VOC: ", "CF: ", "FILE: ", "LINK: ", "EMBED: "]:
        if url.startswith(p):
            url = url[len(p):]
    if url.startswith("/"):
        url = "https://awsacademy.instructure.com" + url

    print(f"  Try: {url[:120]}")
    try:
        cookies = driver.get_cookies()
        ck = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        req = urllib.request.Request(url)
        req.add_header("Cookie", ck)
        req.add_header("User-Agent", driver.execute_script("return navigator.userAgent"))
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        if data[:5] == b"%PDF-":
            fn = "student_guide.pdf"
            cd = resp.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";\n]+)"?', cd)
            if m:
                fn = m.group(1).strip()
            fp = os.path.join(DOWNLOAD_DIR, fn)
            with open(fp, "wb") as f:
                f.write(data)
            print(f"  OK! ({len(data)//1024} KB) -> {fp}")
            return fp
        else:
            print(f"  Not PDF ({resp.headers.get('Content-Type', '?')})")
    except Exception as e:
        print(f"  Fail: {e}")
    return None


def cdp_check(driver):
    """Check performance logs for PDF responses"""
    pdf_urls = []
    try:
        for entry in driver.get_log("performance"):
            try:
                msg = json.loads(entry["message"])["message"]
                if msg.get("method") == "Network.responseReceived":
                    r = msg["params"]["response"]
                    url = r.get("url", "")
                    mime = r.get("mimeType", "")
                    ct = r.get("headers", {}).get("content-type", "")
                    if "pdf" in mime.lower() or "pdf" in ct.lower() or ".pdf" in url.lower():
                        print(f"  CDP found PDF: {url}")
                        pdf_urls.append(url)
            except Exception:
                pass
    except Exception:
        pass
    return pdf_urls


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v4")
    print("=" * 60)
    print(f"Download dir: {DOWNLOAD_DIR}\n")

    print("Starting Chrome...")
    driver = setup()

    try:
        driver.get("https://awsacademy.instructure.com/login")
        print("\n" + "=" * 60)
        print("  Chrome 已開啟！請在 Chrome 中登入 AWS Academy")
        print("  登入完成後回到這裡按 Enter")
        print("=" * 60)
        input("\n>>> ")

        print(f"\nNavigating to Student Guide...")
        driver.get(COURSE_URL)

        print("Waiting for page (5s)...")
        time.sleep(5)

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "iframe"))
            )
        except Exception:
            pass

        print("Waiting for LTI content (20s)...")
        time.sleep(20)

        # CDP check
        print("\n--- CDP Network Check ---")
        cdp_urls = cdp_check(driver)

        # Explore iframes
        print("\n--- Exploring iframes ---")
        driver.switch_to.default_content()
        results = explore_iframes(driver)

        if not results and not cdp_urls:
            print("\nNothing yet, retrying in 15s...")
            time.sleep(15)
            driver.switch_to.default_content()
            results = explore_iframes(driver)
            cdp_urls.extend(cdp_check(driver))

        # Collect candidates
        all_urls = list(set(cdp_urls))
        for r in results:
            rl = r.lower()
            if any(k in rl for k in [".pdf", "download", "readfile", "s3.amazonaws"]):
                all_urls.append(r)

        # Try download
        if all_urls:
            print(f"\n--- Trying {len(all_urls)} candidates ---")
            driver.switch_to.default_content()
            for u in all_urls:
                fp = try_download(driver, u)
                if fp:
                    print(f"\n{'='*60}")
                    print(f"  SUCCESS: {fp}")
                    print(f"{'='*60}")
                    input("\nPress Enter to close...")
                    return
            print("\nDirect download failed.")

        # Fallback: print to PDF
        print("\n--- Fallback: Print to PDF ---")
        driver.switch_to.default_content()

        # Try printing from inside nested iframes
        best_print = None
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, f in enumerate(iframes):
            src = f.get_attribute("src") or ""
            if not src or src == "about:blank":
                continue
            try:
                driver.switch_to.frame(f)
                inner = driver.find_elements(By.TAG_NAME, "iframe")
                for j, inf in enumerate(inner):
                    isrc = inf.get_attribute("src") or ""
                    if not isrc or isrc == "about:blank":
                        continue
                    try:
                        driver.switch_to.frame(inf)
                        # Try even deeper
                        deep = driver.find_elements(By.TAG_NAME, "iframe")
                        for k, df in enumerate(deep):
                            try:
                                driver.switch_to.frame(df)
                                r = driver.execute_cdp_cmd("Page.printToPDF", {
                                    "landscape": False, "printBackground": True
                                })
                                data = base64.b64decode(r["data"])
                                if len(data) > 10000:
                                    fp = os.path.join(DOWNLOAD_DIR, "student_guide_deep.pdf")
                                    with open(fp, "wb") as file:
                                        file.write(data)
                                    print(f"  Deep print ({len(data)//1024}KB): {fp}")
                                    best_print = fp
                                driver.switch_to.parent_frame()
                            except Exception:
                                try:
                                    driver.switch_to.parent_frame()
                                except Exception:
                                    pass

                        if not best_print:
                            r = driver.execute_cdp_cmd("Page.printToPDF", {
                                "landscape": False, "printBackground": True
                            })
                            data = base64.b64decode(r["data"])
                            if len(data) > 10000:
                                fp = os.path.join(DOWNLOAD_DIR, "student_guide_inner.pdf")
                                with open(fp, "wb") as file:
                                    file.write(data)
                                print(f"  Inner print ({len(data)//1024}KB): {fp}")
                                best_print = fp
                        driver.switch_to.parent_frame()
                    except Exception:
                        try:
                            driver.switch_to.parent_frame()
                        except Exception:
                            pass
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

        if not best_print:
            # Print main page as last resort
            try:
                driver.switch_to.default_content()
                r = driver.execute_cdp_cmd("Page.printToPDF", {
                    "landscape": False, "printBackground": True
                })
                data = base64.b64decode(r["data"])
                fp = os.path.join(DOWNLOAD_DIR, "student_guide_page.pdf")
                with open(fp, "wb") as file:
                    file.write(data)
                print(f"  Page print ({len(data)//1024}KB): {fp}")
                best_print = fp
            except Exception as e:
                print(f"  Print failed: {e}")

        if best_print:
            print(f"\n{'='*60}")
            print(f"  PDF saved: {best_print}")
            print(f"  (print version, not original)")
            print(f"{'='*60}")
        else:
            print("\nAll methods failed.")
            if results:
                print("\nAll URLs found:")
                for i, r in enumerate(results, 1):
                    print(f"  [{i}] {r}")

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
