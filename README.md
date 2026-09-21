# AWS Academy Student Guide PDF 下載器

此專案用於自動下載 AWS Academy 課程中，被 LTI 與 Canvas LMS 隱藏且無提供下載按鈕的嵌入式 PDF 教材 (Student Guide)。

## 腳本原理
教材透過深層跨域 iframe (OOPIF) 及客製化 PDF.js (Rustici SCORM player) 渲染，無法直接取得檔案 URL。
本腳本使用 **Selenium + CDP (Chrome DevTools Protocol)**，透過 `Page.addScriptToEvaluateOnNewDocument` 在所有 iframe 建立前注入 **JavaScript Hook**。
當網頁準備呼叫 `window.pdfjsLib.getDocument` 載入 PDF 時，Hook 會攔截這個 Promise，並將完成的 `pdfDoc` 物件保存到全域變數中。隨後 Python 腳本只需遍歷所有的 iframe 結構，就能直接從記憶體中提取出 PDF 二進位資料並存檔。

## 檔案介紹
* `grab_student_guide_v11.py`：正式版本，支援任意 Module URL 與批次下載。
* `失敗腳本/`：包含 v1 到 v10 的開發過程與測試版本（保留作參考）。
* `downloads/`：存放下載結果的 PDF 檔案（已加入 `.gitignore`，不會被推送到 GitHub）。

## 執行方式與結果
**環境準備**：確保已安裝 Python 與 Chrome，並安裝依賴：
```bash
pip install -r requirements.txt
```

**單一下載**：
```bash
python grab_student_guide_v11.py "https://awsacademy.instructure.com/courses/188219/modules/items/18606619"
```

**批次下載**（一次登入，逐個下載）：
```bash
python grab_student_guide_v11.py URL1 URL2 URL3
```

**互動模式**（不帶參數，手動貼上 URL）：
```bash
python grab_student_guide_v11.py
```

腳本會自動開啟 Chrome 視窗，請手動登入 AWS Academy 後按 `Enter`。每個 URL 等待約 30 秒讓 LTI 與 PDF 播放器完全渲染，接著自動從頁面標題產生檔名（如 `100-ACCLFO-20-EN-M02SG.pdf`），並將 PDF 儲存至 `downloads/`。

## 踩坑紀錄與失敗原因 (v1-v9)
* **找不到網路請求檔案**：一開始透過瀏覽器 Network Tab 什麼都抓不到。因為 PDF 並非以單一 `*.pdf` 檔案傳輸，而是由 PDF.js 使用 Range requests (分塊請求) 載入，並在 HTML Canvas 上渲染。
* **Canvas API 無權限 (v1-v3)**：嘗試呼叫 Canvas 官方 API，但出現 403 錯誤。因為教材是由外部工具 (Vocareum/ContentController) 透過 LTI 掛載，不屬於 Canvas 的原生檔案系統。
* **無法直接列印 (v4-v5)**：嘗試呼叫 Chrome CDP 的 `Page.printToPDF`，但只印出 Canvas 外層的「封面」。真實內容被跨域 iframe (Cross-Origin iframe) 安全機制隔離。
* **CDP 網路封包攔截失敗 (v6-v7)**：就算使用 CDP 監聯底層網路封包，因為內容是由第三方 CDN 加上複雜的授權 Token 提供，且分段下載，難以重組完整檔案。
* **變數被閉包隱藏 (v8-v9)**：雖然成功定位到負責渲染的 iframe 與 PDF.js，但該客製化播放器沒有暴露標準的 `PDFViewerApplication` 全域變數，重要物件被封裝在閉包 (Closure) 中，無法直接用常規 JavaScript 提取。
* **v10 單一 URL 限制**：v10 成功實現 Hook 攔截法，但硬編碼了 Module 2 的 URL，無法適用其他模組。於 v11 改為參數化設計。
