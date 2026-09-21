"""
AWS Academy Student Guide PDF Downloader v10 (Ultimate Hook Method)

策略：
使用 CDP 的 Page.addScriptToEvaluateOnNewDocument，在每個 iframe 建立時，
預先注入 JavaScript Hook。當網頁嘗試設定 `window.pdfjsLib` 並呼叫
`getDocument` 下載 PDF 時，我們攔截這個 Promise，並將 PDFDocument 
物件保存到 `window.__interceptedPDFDoc` 中。
之後只要遍歷所有 iframe，把 PDF 提取出來即可。
"""

import os
import time
import base64

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

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

    # 在所有 frame (包含 OOPIF) 載入前，預先注入 Hook 腳本
    hook_script = """
    (function() {
        // 攔截 window.pdfjsLib
        let _pdfjsLib = window.pdfjsLib;
        Object.defineProperty(window, 'pdfjsLib', {
            configurable: true,
            enumerable: true,
            get: function() {
                return _pdfjsLib;
            },
            set: function(val) {
                _pdfjsLib = val;
                if (val && val.getDocument && !val._isHooked) {
                    val._isHooked = true;
                    const origGetDocument = val.getDocument;
                    val.getDocument = function() {
                        const task = origGetDocument.apply(this, arguments);
                        // 當 PDF 載入完成，攔截 pdfDoc 物件
                        task.promise.then(pdfDoc => {
                            window.__interceptedPDFDoc = pdfDoc;
                        }).catch(e => {});
                        return task;
                    };
                }
            }
        });
        
        // 備用：攔截 XHR 避免使用 Range requests 的情況
        const origOpen = XMLHttpRequest.prototype.open;
        const origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._url = url;
            origOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function() {
            this.addEventListener('load', function() {
                try {
                    if (this.responseType === 'arraybuffer' || this.responseType === 'blob') {
                        // 讓它過去
                    } else if (this.responseText && this.responseText.substring(0,4) === '%PDF') {
                        window.__interceptedRawPDF = this.responseText;
                    }
                } catch(e) {}
            });
            origSend.apply(this, arguments);
        };
    })();
    """
    
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": hook_script
    })
    
    return driver


def extract_from_frames(driver, depth=0, max_depth=6):
    """遞迴搜尋所有 frame 尋找被我們攔截到的 PDF 物件"""
    if depth > max_depth:
        return None

    indent = "  " * depth

    try:
        url = driver.execute_script("return window.location.href")
        print(f"{indent}[Frame] {url[:100]}")

        # 檢查是否有攔截到 PDF
        has_pdf = driver.execute_script("return !!window.__interceptedPDFDoc;")
        if has_pdf:
            print(f"{indent}🎯 找到被攔截的 PDFDocument！正在提取資料...")
            pdf_b64 = driver.execute_script("""
                return window.__interceptedPDFDoc.getData().then(function(data) {
                    var binary = '';
                    var bytes = new Uint8Array(data);
                    var len = bytes.byteLength;
                    // 分塊轉 Base64
                    var CHUNK = 8192;
                    for (var i = 0; i < len; i += CHUNK) {
                        var slice = bytes.subarray(i, Math.min(i + CHUNK, len));
                        binary += String.fromCharCode.apply(null, slice);
                    }
                    return btoa(binary);
                });
            """)
            if pdf_b64:
                return base64.b64decode(pdf_b64)
                
        # 檢查備用 raw PDF
        has_raw = driver.execute_script("return !!window.__interceptedRawPDF;")
        if has_raw:
            print(f"{indent}🎯 找到被攔截的 Raw PDF！")
            raw = driver.execute_script("return window.__interceptedRawPDF;")
            return raw.encode('latin1')

    except Exception as e:
        pass

    # 搜尋子 frame
    try:
        iframe_count = driver.execute_script("return document.querySelectorAll('iframe').length")
        for i in range(iframe_count or 0):
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


def main():
    print("=" * 60)
    print("  AWS Academy Student Guide PDF Downloader v10 (JS Hook)")
    print("=" * 60)

    driver = setup()

    try:
        driver.get("https://awsacademy.instructure.com/login")
        print("\n  👉 請在 Chrome 中登入 AWS Academy")
        print("  👉 登入完成後回到這裡按 Enter")
        input("\n>>> ")

        print(f"\n正在導航到 Student Guide...")
        driver.get(COURSE_URL)

        print("等待頁面與 PDF 完全載入 (30 秒)...")
        time.sleep(30)

        print("\n--- 開始掃描並提取 PDF ---")
        driver.switch_to.default_content()
        pdf_data = extract_from_frames(driver)

        if pdf_data and pdf_data[:5] == b"%PDF-":
            fp = os.path.join(DOWNLOAD_DIR, "student_guide.pdf")
            with open(fp, "wb") as f:
                f.write(pdf_data)
            print(f"\n{'='*60}")
            print(f"🎉🎉 成功！PDF 已儲存至:")
            print(f"📁 {fp} ({len(pdf_data)//1024} KB)")
            print(f"{'='*60}")
        else:
            print("\n❌ 提取失敗。")

        input("\n按 Enter 關閉瀏覽器...")

    except KeyboardInterrupt:
        print("\n使用者中斷")
    except Exception as e:
        print(f"\n發生錯誤: {e}")
        input("按 Enter 關閉...")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
