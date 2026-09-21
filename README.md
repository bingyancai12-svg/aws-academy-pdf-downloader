# AWS Academy Student Guide PDF 下載器

此專案用於自動下載 AWS Academy 課程中，被 LTI 與 Canvas LMS 隱藏且無提供下載按鈕的嵌入式 PDF 教材 (Student Guide)。

## 腳本原理 (v11 最終版)
教材透過多達 4 層的深層跨域 iframe (OOPIF) 及客製化 PDF.js (Rustici SCORM player) 渲染。
為了解決跨域框架難以注入 JavaScript Hook 的問題，v11 採用了 **Performance API 輪詢監聽法**：
1. **導航與等待**：Selenium 進入最深層的 PDF viewer iframe (d4 frame)。
2. **網路輪詢**：透過 JavaScript 持續輪詢 `performance.getEntriesByType('resource')`，等待 cmi5 驗證完成並開始載入 PDF。
3. **攔截與下載**：一旦偵測到含有 `.pdf` 的真實請求 URL 出現，立即呼叫同源的 `fetch()` 將檔案抓取進記憶體，並轉為 Base64 傳回 Python 存檔。

## 檔案介紹
* `grab_student_guide_v11.py`：正式版本，支援任意 Module URL 與批次下載。
* `失敗腳本/`：包含 v1 到 v10 的開發過程與測試版本（保留作技術參考，包含 Canvas API、JS Hook 等失敗嘗試）。
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

腳本會自動開啟 Chrome 視窗，請手動登入 AWS Academy 後按 `Enter`。腳本會自動等候 LTI 與 PDF 播放器驗證（最高輪詢等待 120 秒），接著自動從頁面標題產生檔名，並將 PDF 儲存至 `downloads/` 資料夾。

## 踩坑紀錄與失敗原因 (v1-v10)
* **找不到網路請求檔案**：透過瀏覽器 Network Tab 單純監聽抓不到完整檔案。PDF.js 使用 Range requests (分塊請求) 載入並在 Canvas 渲染。
* **Canvas API 無權限 (v1-v3)**：嘗試呼叫 Canvas 官方 API 出現 403 錯誤。教材是透過 LTI 掛載的外部工具 (Vocareum/ContentController)，不屬於 Canvas 原生檔案系統。
* **無法直接列印 (v4-v5)**：呼叫 Chrome CDP `Page.printToPDF` 只印出外層「封面」，真實內容被跨域 iframe 安全機制隔離。
* **CDP 網路封包攔截失敗 (v6-v7)**：第三方 CDN 加上複雜授權 Token 且分段下載，難以重組檔案。
* **變數被閉包隱藏 (v8-v9)**：成功定位 iframe 後，客製化播放器沒有暴露標準的 `PDFViewerApplication`，變數被封裝在閉包 (Closure) 中，無法提取。
* **JS Hook 攔截法 (v10)**：使用 CDP `Page.addScriptToEvaluateOnNewDocument` 注入 Hook 攔截 Promise，但在 Chrome 的 OOPIF (Out-of-Process iframes) 機制下經常無法穩定命中對應的 context。
* **最終解法 (v11)**：捨棄提前注入，改為載入後持續輪詢底層 Performance API 取出真實 URL，並進行同源 `fetch()` 下載。
