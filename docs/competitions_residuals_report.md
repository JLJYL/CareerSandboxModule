# 競賽技能標註報告（給成員 B 覆核）

受限選擇版：LLM 直接從詞彙表 name_zh 挑，輸出保證對齊，無正規化殘留。

- 競賽總數：65
- 標到技能：27（2026-10-24 後端覆核後；原 29，詳見下方修正）
- 標不到（純建築／藝術／數學等，與職能詞表關聯弱，屬正常）：38（原 36）

## 2026-10-24 後端回報後的覆核修正

Yuna 匯入後對照 tags 挑出 4 筆可疑標註，模型組覆核。資料無 description 欄，標註本就只能憑
title／category／tags；覆核原則：技能須有 tag 或標題訊號支持，平台分類字（DevPost 的
Communication、AWS 產品名）不算技能訊號，泛詞（Design）無乾淨詞條對應則留空。

| 序號 | sourceId | 原 skills | 改為 | 理由 |
|---|---|---|---|---|
| c8 | devpost-31052 | 溝通能力, 機器學習 | 機器學習 | Communication 是 AWS CDS 產品名，非軟技能 |
| c22 | devpost-31666 | 溝通能力, 機器學習 | 資訊安全, 機器學習 | Communication 是 DevPost 分類；補原本漏標的資訊安全（Cybersecurity tag＋標題 systems security） |
| c33 | devpost-30500 | 機器學習 | （空） | tags（Beginner Friendly／Low-No Code／Open Ended）無任何 ML 訊號，原標屬臆測 |
| c60 | devpost-31715 | 設計導入製造執行系統(MES) | （空） | MES 為製造術語，與教育類黑客松無關；Design tag 太泛、無乾淨具體設計詞條可定錨 |

## 標不到技能的競賽

- 第十五屆全國大專院校盃原創桌上遊戲設計比賽
- FLOATING TABLE 國際建築競賽
- 2026 第六屆全國VR跨域盃【SDGs 虛擬實境大賽】
- 2026年第二屆雙福三創盃競賽
- 2027智慧城市創新應用獎
- 115年新竹縣青春靚點子 全國學生創業挑戰賽
- 2026 THD Award 手繪設計獎 校園知識場域再生計畫
- 2026 國立清華大學「清華光罩教學獎」
- 2026最佳規劃論文獎：未來城市與都市化
- TWEL 2026全國大專青年樂齡防跌影片創意競賽
- THE STUDENTS APARTMENT Competition
- 2026 第二十屆波蘭國際發明展暨發明競賽
- 第十屆青年公益實踐計畫
- Ruinas de Quilmes 奎爾梅斯遺址遊客中心與露天博物館建築設計競賽
- 2026 全國低碳生活企劃專題競賽
- LaunchPad Hacks
- Underbridge #2 – Urban Infrastructure Architecture Competition
- 2026 全國大專院校暨高中職競賽 共融未來：跨文化便利商店創新設計競賽 Future Nexus Store Challenge 2026
- 2026年第三屆摩洛哥青年建築師獎 Young Moroccan Architecture Awards 3ème Edition 2026
- Future Snack Design
- 2026 Buildner 未建成建築大獎競賽 (BN Er UNBUILT AWARD 2026)
- 2027 WMI世界數學邀請賽‑臺灣選拔賽
- 2026 AYDA Awards 國際學生競圖
- 第五屆群馥盃圖案設計大賽
- 【2026第十四屆國際青年華嚴學者論壇】徵稿啟事
- 2026 Pavilion Atlas 建築競賽
- 2026 國際競圖公開徵件
- 2026 KidWind 風力能源亞洲聯賽
- 115 年「創意狂想 巢向未來」 智慧化居住空間創意競賽
- Open Chair 開放式家用3D列印椅子國際概念競賽
- Vancouver Tall Challenge International Architecture Competition
- The Architect’s Chair斯德哥爾摩傢俱展特別版建築師座椅競賽
- 2027 醫藥先鋒盃 全國學生生醫競賽
- 紐約高瀑布河濱市場New York High Falls Riverfront Market國際建築設計競賽
- 2026《協易盃》大手攜小手~伺服沖壓創新應用競賽
- The Quiet Tower 寂靜之塔國際建築設計競賽
- DSH Hacks V2 ($100k+ in prizes)（2026-10-24 覆核改判：原標 機器學習，無 tag 支持）
- The Arcticathon（2026-10-24 覆核改判：原標 MES，誤標）
