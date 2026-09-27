# ALASKA Camera 來源與取得核查（2026-09-27）

結論：**官方分享連結已過期；本輪不能取得並核查 Camera archive。**
HTTP 200 返回的是 SharePoint 錯誤 HTML，不是成功下載。尚未確認實際
archive 的 SHA-256、內部 schema、授權 notices、標註一致性或固定 cohort
資格。因此不能宣稱資料已 qualified、模型已擬合或外部驗證完成。

## 已實際開啟的第一手來源

- [官方 repository](https://github.com/merialdo/research.alaska) 及其
  [README](https://raw.githubusercontent.com/merialdo/research.alaska/main/README.md)：
  Camera 列 29,787 筆 records、24 個 sources、103 個 entities、3,865 筆
  annotated records，下載標示 8.6 MB。這是 provider 宣告，不是本輪 archive
  實測值。ER mapping 的欄位為 `entity_id,spec_id`；規格內容是 JSON。
- [論文 v2 全文](https://arxiv.org/html/2101.11259v2)：§3.2 定義 entity 等價關係；
  §3.3 指標針對 manually verified subset，並規定其正負 pair 形成完整子圖；
  §4 說明目標 entities 的完整 matches；§5 說明 reference 的 transitive closure。
  這支持只在官方 annotated records 上建立完整 reference 的解讀，不能把其餘
  未標註 records 當 singleton。資料仍屬產品領域，並非相對 WDC 的新語義領域。
- [repository LICENSE](https://raw.githubusercontent.com/merialdo/research.alaska/main/LICENSE)：
  MIT、Copyright 2021 Paolo Merialdo，其文字對象是軟體及相關文件。不能據此
  自動批准下載 archive 內第三方產品資料的公開再散發。若將來成功取得，仍須
  核查 archive notices；本轮公開包不含原始／逐記錄 Camera 資產。
- [官方 repository issue #2](https://github.com/merialdo/research.alaska/issues/2)：
  2026-07-29 已有使用者回報下載連結過期。查核時未見官方替換下載連結。
  這只作與本輪 HTTP 實測一致的旁證；沒有發送訊息或要求作者處理。

## 實際 transport 查核

README 的 Camera 連結為 `http://bit.ly/camera_data`；使用同一路徑的 HTTPS
做唯讀 HEAD／GET。它重新導向 Roma Tre 的公開 SharePoint 分享頁，頁面 title
為 `Errore`，正文說明分享連結到期。`download=1` 查核也仍為 HTML。
未下載、執行或解開第三方研究資料／程式。

安全紀錄在 `outputs/session_20260927_v6/provider_review/transport.json`，包含
實際命令、UTC 時間、exit codes、挑選過的 headers、錯誤摘要及回應文字 hash。
沒有保存 cookie 或完整 SharePoint HTML。該 hash 是 PowerShell 擷取後的 UTF-8
文字 hash，**不是 archive hash**；實際 archive bytes 仍未知。

最初受限 shell 的 Python TLS 查核失敗，curl 的 Schannel 亦報
`SEC_E_NO_CREDENTIALS`。經准許的唯讀 shell 重試成功連到官方頁後，確認真正
阻擋是過期分享連結；沒有停用 TLS 驗證，也沒有用非官方鏡像替代。

## 對本輪研究的處理

新 V6 協議、獨立 qualification／prefit／repair 入口及其合成正確性測試仍交付。
root 在 source freeze 完成後將外部分支的全部 21 格標為
`not_started_download_blocked`，記錄 0 個 archive download、0 次 fit、0 次 repair。
V5 的 21 格 `not_started_gate` 完全保留；兩次缺失原因不可混合。
不改 Camera 類別、benchmark、seed 或分組，不以既有或合成結果補位。
