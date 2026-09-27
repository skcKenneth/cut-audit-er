# CUT-AUDIT-ER

[English](README.md) · [原始程式](https://github.com/skcKenneth/cut-audit-er) · [Pages 成果頁](https://skcKenneth.github.io/cut-audit-er/)

本庫提供 **Certified Proxy Search in Verification-Only Entity Repair: Coverage, Realized Value, and Cost** 的研究程式、V7.1 證據、六張圖及有限重現檢查。研究限制是逐 pair 付費查詢，只刪除已驗證為負的邊。

保留的 241 個自然資料 Full 選擇，全部經核查為各自搜尋池內的實作 proxy 最大值；但九個自然 cohort–budget 對比中，Full 與 Raw 的終點及付費序列均相同。池內認證不代表修復品質最優。四個固定構造控制分開展示事後資訊優勢與期望決策差距；精確 pair 邊際概率只屬這些構造機率律，不能據此認定自然 matcher 已完美校準，或將自然資料差距歸因為同一機制。

研究決策仍為 **REFRAME**，不宣稱已獲接受、普遍優越或完成新的外部驗證。本次 repository 整理只修改呈現及發布支援，沒有新增 selector、實驗、資料、訓練、調參或封存 test 存取。論文全文與私人審查材料不在公開庫內。

## 閱讀次序

1. `evidence/` 與 `figures/`：保留結果、負面證據、缺失及六圖。
2. [重現範圍](REPRODUCTION_SCOPE.md)：公開材料能核查甚麼，以及仍依賴甚麼外部資產。
3. [第三方來源與授權](THIRD_PARTY_NOTICES.md)：MIT 軟體授權不取代 DBLP 衍生資料的 CC BY 4.0。
4. `src/`、`scripts/`、`tests/`：實際程式與有限正確性測試。
5. `historical/v5/`：保存引擎、合成及 DBLP 已付費答案回放。

WDC 只公開彙總；公開表不能核對私人 pair 身分或重建自然圖。合成控制不是自然資料結果，二十個有限世界也不是二十個獨立樣本。原生 TransClean／GraphCR 比較未完成；adapter 不等於原方法完整重現。

## 執行有限驗證

完整命令見 [英文 README](README.md#finite-verification)。使用 Python 3.12、固定依賴、單執行緒及全新輸出目錄。驗證包括有限 fixtures、精確控制計算、保留證據、六圖數值投影及網站資產。跨作業系統圖檔可能有渲染差異，因此不宣稱 PDF 二進位逐 byte 一致。

歷史回放必須在 `historical/v5` 執行三份 bundle；只用已保存付費答案，遇到未記錄查詢便失敗，不從 evaluator gold 補答。這些回放不是重新取得自然資料答案，亦不是重跑全部歷史研究。

## 發布與保留紀錄

[GitHub Actions](.github/workflows/ci.yml) 通過測試、證據核對、回放、製圖及網站檢查後，才可由 `main` 分支部署 Pages。工作流程不下載研究資料、訓練或執行修復矩陣。是否已完成遠端部署，以該 commit 的 Actions／Pages 紀錄為準；靜態網站建置本身不宣告上線。

舊交付包的檔案清單放在 [provenance/archive_manifests](provenance/archive_manifests/)，用途是追查原版來源，不代表整理後目錄仍包含每一份舊呈現副本。科學來源、已保存結果、失敗及回放依賴維持保留；整理後的完整性由本版 manifest 與驗證器核對。完整工作區、公開有限測試、回放及遠端 CI 各有不同範圍，不能混稱完整歷史重現。