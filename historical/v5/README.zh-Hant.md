# Cut Audit ER — V5

這個本地交付研究「候選補全」與「按 proxy 上界篩選」能否改善 verification-only 群集修復。新增方法不等於取得正面結果，亦不代表獲接納、已部署或優於現有原生方法。

**實際結果：維持REFRAME。** 新法與raw在9組自然條件的loss及付費序列全部相同，成本增加。合成k3/B6反例得到修正，但與BC及新singleton同分。預定開發門檻未通過，ALASKA21格全部未啟動；沒有Camera下載、模型擬合或外部查詢，不能把這21格稱作benchmark運行失敗。

請先讀 `evidence/manifest.json` 的完整計數及缺失狀態，再看六張圖和 `evidence/contrasts.csv`。150次合成 acquisition 對應300組相依 H0/H9 評估；63格自然開發對照及21格有条件的外部槽位全部列出。相關預算、同一 benchmark 的 cohorts、逐次查詢均不是獨立樣本。逾時前綴不填補完整終點。

七個自然方法包括 weighted BC、原 fixed／adaptive planner、候選補全加舊 BC cap、舊池加上界篩選、完整新方法及新 singleton 控制。評估 gold、FN headroom 及離線界限不進入 selector。上界只約束原 proxy 的浮點實作，不保證真實收益或 FN 安全。

執行方法見英文 README。使用 Python3.12、固定依賴、CPU1及單執行緒環境，依次做有限 pytest、表格／hash 核查、三個已付費答案回放、六圖重建與靜態網站建置。輸出目錄必須全新。合成 correctness fixtures 是程式測試，不計作研究結果。

`replay/` 提供合成與兩個 DBLP 圖的可核查代號化資料；遇到未記錄查詢必須失敗，不准從 evaluator reference 補答。`historical/v4/` 保留原有完整公開版本與其失敗紀錄。WDC 只提供彙總；跨版本時間不混合排名。

論文全文留在私人 Overleaf／審查包。這個 repository ZIP 不含原始文字、原始 IDs、反向表、WDC 原始或逐記錄資產、憑證或封存 test。完整歷史重算仍需要外部封存資產及各自授權，不能把本包的有限測試／回放稱為全部實驗重現。
