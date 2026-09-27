# CUT-AUDIT-ER · V4 證據檢查包

**在只能刪除已驗證負邊的限制下，區分「機會 → 實際使用 → 增量效果」。**
[English](README.md)

這個本機檢查包含第一方程式、已保存的研究證據、有限回放資產、六張圖及
輕量中英雙語網站。英文論文、Overleaf 原始碼及私人審查材料另行交付 ZIP。
本包不代表已達會議投稿水平，也不宣稱方法普遍優越。本輪交付不包括 GitHub
推送、遠端工作流程或 Pages 部署。

## 三類證據分開閱讀

| 證據 | 固定範圍 | 可以支持甚麼 |
|---|---|---|
| 已暴露 development 圖 | 原有 WDC／DBLP–ACM 的18格 requested-budget 運行 | 局部機制差異及失敗案例；這些圖已參與研究開發。 |
| 受控合成圖族 | 計畫90次 selector 執行、180組相依的離線參考評估 | 在指定構造內檢查割集機會、是否使用及終點差異；兩份參考共用查詢，不是180個獨立觀察。 |
| 原先未使用的 DBLP–ACM cohort | 核查全部910筆省略記錄的資格，最多九格固定方法／預算比較 | 資格成立後的有限同 benchmark 檢查；不是另一語義領域，也不是封存 test。 |

**實際完成數、資格狀態與付費上下界以 `evidence/manifest.json` 為準。**
計畫格數不等於已完成格數。缺失終點保留缺失，不能用已保存前綴補成完整
requested-budget 結果。網站數字與表格直接取自這份 manifest 及正式 CSV。

本次 V4 已完成 **89／90次合成 acquisition、178／180組參考評估**；一格因
執行中斷而缺失，沒有重跑。其未知付費數令整體實際查詢成本保留為
**287–288**。取得資格的 DBLP cohort 完成 **9／9格**；完成不等於有研究收益。

主要指標維持 **FP+FN**；raw–singleton 及 raw–BC 差值保留零效應、退步與
FN 取捨。Gold 結構量及全知界限只作離線診斷，不交給 selector。精確界限不
計取得未知答案的成本，並非自適應策略保證。基本記帳、有限割集與快取不
自行視為新穎貢獻。

## 在本機檢查

使用 **Python 3.12** 及固定版本依賴，在本包根目錄執行：

```sh
python -m pip install -r requirements-public.txt
python -m pip install --no-deps -e .
python -m pytest -q
python scripts/validate_evidence.py --evidence evidence
python scripts/check_bundled_replays.py --root . --receipt build/replay_check.json
python scripts/make_figures.py --evidence evidence --out build/figures
python scripts/build_site.py --out _site --figures build/figures
python -m http.server 8765 --directory _site
```

打開 `http://localhost:8765` 閱讀雙語網站；生成的 HTML 亦可直接離線打開。
再次建站請指定新的輸出目錄。來源 hash、圖表來源或回放內容不一致便拒絕
檢查，不能用新 oracle 查詢補回缺失答案。

在啟動 Python 前設定 `PYTHONHASHSEED=0`，並把 OMP、OpenBLAS、MKL 執行緒
各固定為1。PowerShell 寫法：

```powershell
$env:PYTHONHASHSEED='0'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
```

附帶 CI 使用 Python 3.12 及相同設定，只檢查程式測試、既有證據、回放、圖
與網站，不下載 benchmark、不訓練、不重新取得答案或執行研究格。可選 Pages
部署預設關閉，須另行明確要求手動啟動；本機通過不代表遠端 CI 或部署通過。

## 檔案與重現邊界

- `evidence/`：真實資料及合成資料表、歷史缺失、manifest 與成本／完成狀態；
  合成 acquisition 成本只計一次。
- `replay/synthetic/{study,analysis}/`：合成輸入、已付費答案及完整離線證據；
  檢查候選順序、partition 及兩份參考評估，沒有新查詢。
- `replay/dblp_exposed/`：指定 DBLP 已保存答案的回放包。
- `replay/dblp_unused/`：只有取得資格且有完整可回放案例才提供。缺包會明列，
  不另換 cohort 補位。
- `src/cut_audit_er/`、`tests/`：實際第一方引擎與有限正確性測試；軟件測試
  與正式合成研究分開計數。
- `figures/`：六圖 `fig01_contract`、`fig02_structure`、`fig03_outcomes`、
  `fig04_events`、`fig05_controlled`、`fig06_use`，含 PDF／SVG／PNG。
- `site/`、`scripts/build_site.py`：只使用已驗證證據的靜態雙語閱讀入口，
  無帳號、追蹤或付費服務。

合資格 DBLP 回放包含保留排序的別名、固定 scores、付費答案，以及分離的
離線參考；不包括原始記錄 ID 或書目文字。WDC 的 pair 身分與完整重建資產
不再散發，公開事件算術不能獨立驗證私人身分分歧核查。請併讀
[重現範圍](REPRODUCTION_SCOPE.md)及[來源聲明](THIRD_PARTY_NOTICES.md)。

精簡包不能獨立重算全部歷史實驗；未附的凍結資產及權限須按文件另行取得。
保留所有歷史失敗與42格未運行比較。`mincut_proxy` **不是 TransClean 的完整
重現**；未完成的原生 GraphCR／TransClean 比較亦不支持 SOTA 排名。
