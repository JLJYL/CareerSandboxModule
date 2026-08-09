"""Atlas 落地工具（W3 收尾）：把 KB 種子＋文章切塊寫進 MongoDB Atlas。

落地目標 collection 為 `career_knowledge`，欄位對應依 CONTRACTS.md #3：

    _id ← KBEntry.id / text ← content / type,title,skills 原樣
    source ← metadata.source（提到頂層供 filter）
    metadata 整包保留（含 industry，向量索引 filter 走 metadata.industry）
    embedding[1024] ← bge-m3

安全原則：URI 預設從環境變數 / .env 讀，不從命令列傳（PowerShell 會把
命令列寫進 ConsoleHost_history.txt 純文字檔）。任何輸出一律遮蔽帳密。

典型流程：

    python tools/ingest_atlas.py --dry-run                    # 不連線,先驗資料
    python tools/ingest_atlas.py --create-index               # 落地＋建索引
    python tools/ingest_atlas.py --smoke "轉職資料分析要準備什麼"  # 煙霧測試
    python tools/ingest_atlas.py --print-index-json           # 改用 Atlas UI 貼索引
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.config import settings  # noqa: E402,F401  副作用:載入 .env
from app.providers.embeddings import EMBEDDING_DIM  # noqa: E402
from app.retrieval.vector_retriever import DEFAULT_SEEDS  # noqa: E402
from app.schemas.domain import KBEntry  # noqa: E402

INDEX_DEF_PATH = REPO / "fixtures" / "atlas" / "vector_index.json"
DEFAULT_VECTOR_CACHE = REPO / "data" / "kb_index.json"
DEFAULT_COLLECTION = "career_knowledge"      # 合約固定,不要改
REQUIRED_PROVIDER = "BgeM3Embedding"         # 快取必須是真向量,不收 FakeEmbedding


# --------------------------------------------------------------- 工具
def mask_uri(uri: str) -> str:
    """遮蔽帳密與 host,只留 scheme 與 database,可安全寫進 log 與驗收紀錄。"""
    if not uri:
        return "(empty)"
    return re.sub(r"://[^@]*@[^/?]*", "://<redacted>@<redacted>", uri)


def resolve_uri(cli_uri: str | None) -> str:
    uri = cli_uri or os.getenv("MONGODB_URI", "")
    if not uri:
        sys.exit("找不到 URI。請在 .env 加 MONGODB_URI=...（.env 已在 .gitignore），"
                 "或用環境變數；不建議走 --uri，命令列會留在 shell 歷史。")
    if cli_uri:
        print("[warn] 你用了 --uri：URI 會留在 shell 歷史紀錄裡。"
              "落地完成後請清理歷史，並改用 .env。", flush=True)
    return uri


def make_client(uri: str, appname: str, connect: bool = True):
    """統一建 client:把 mongodb+srv 的 DNS 失敗轉成看得懂的訊息。"""
    from pymongo import MongoClient
    from pymongo.errors import ConfigurationError
    try:
        return MongoClient(uri, appname=appname, connect=connect,
                           serverSelectionTimeoutMS=15000)
    except ConfigurationError as e:
        if "DNS" in str(e) or "_mongodb._tcp" in str(e):
            sys.exit("URI 的 cluster 主機名稱查不到（DNS SRV 解析失敗）。"
                     "請回頭核對 .env 裡的 URI 有沒有貼漏或被截斷——"
                     "密碼含 # 會被 config.py 從 # 切掉。\n"
                     f"原始訊息：{str(e)[:160]}")
        raise


def resolve_db(cli_db: str, uri: str) -> str:
    """--db / MONGODB_DB 優先;沒填就取 URI 路徑上的預設 database。"""
    if cli_db:
        return cli_db
    from pymongo.errors import ConfigurationError
    try:
        name = make_client(uri, "career-sandbox-check", connect=False
                           ).get_default_database().name
    except ConfigurationError:
        name = None
    if not name:
        sys.exit("缺 database 名稱。請在 .env 加 MONGODB_DB=，"
                 "或在 URI 路徑補上（…mongodb.net/<db>?…）。")
    print(f"[db] 未指定 --db，採用 URI 路徑上的預設 database：{name}")
    return name


def run_check(uri: str, db_name: str, coll_name: str, index_name: str) -> None:
    """只讀檢查:連線、目標 DB 現況、既有索引、目前角色。不寫入任何資料。"""
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

    client = make_client(uri, "career-sandbox-check")
    try:
        info = client.admin.command("ping")  # noqa: F841
        build = client.admin.command("buildInfo")
    except ServerSelectionTimeoutError as e:
        sys.exit(f"連不上 Atlas（{type(e).__name__}）。最常見原因是 Atlas 的 "
                 "Network Access 沒有把你目前這台機器的 IP 加進白名單；"
                 "其次是 .env 的 URI 被截斷（密碼含 # 會被 config.py 切掉）。\n"
                 f"原始訊息：{str(e)[:200]}")
    print(f"[check] 連線 OK — MongoDB {build.get('version', '?')} "
          f"／ {mask_uri(uri)}")

    try:
        roles = client.admin.command("connectionStatus")["authInfo"].get(
            "authenticatedUserRoles", [])
        print("[check] 目前角色：" + (", ".join(
            f"{r.get('role')}@{r.get('db')}" for r in roles) or "(無)"))
    except PyMongoError as e:
        print(f"[check] 無法讀取角色資訊（{type(e).__name__}），可略過")

    db = client[db_name]
    existing = sorted(db.list_collection_names())
    print(f"[check] database `{db_name}` 現有 {len(existing)} 個 collection：")
    for c in existing:
        mark = "  <= 目標" if c == coll_name else ""
        print(f"          {c} ({db[c].estimated_document_count()} 筆){mark}")
    if coll_name not in existing:
        print(f"          （`{coll_name}` 尚不存在，落地時會新建）")

    try:
        idx = list(db[coll_name].list_search_indexes())
        if idx:
            for ix in idx:
                print(f"[check] 既有向量索引：{ix.get('name')} "
                      f"status={ix.get('status')} queryable={ix.get('queryable')}")
        else:
            print(f"[check] 尚無向量索引（預定建立 `{index_name}`）")
    except PyMongoError as e:
        print(f"[check] 讀不到 search index 清單（{type(e).__name__}）："
              "可能是權限不足或叢集層級不支援，建索引時改走 Atlas UI。")

    print("\n[check] 完成，未寫入任何資料。")
    client.close()


def load_entries(seed_paths=DEFAULT_SEEDS) -> dict[str, KBEntry]:
    """與 VectorRetriever 完全相同的載入邏輯,確保 Atlas 內容 == 本機索引內容。"""
    entries: dict[str, KBEntry] = {}
    for p in seed_paths:
        for raw in json.loads(Path(p).read_text(encoding="utf-8")):
            e = KBEntry.model_validate(raw)
            if e.id in entries:
                sys.exit(f"種子檔 id 重複：{e.id}")
            entries[e.id] = e
    return entries


def load_cached_vectors(path: Path, ids: list[str],
                        allow_partial: bool = False) -> dict[str, list[float]] | None:
    """讀 build_kb_index.py 產生的持久化快取,省下 587 條重算的十幾分鐘。

    id 集合不吻合時預設整包不採用(保守)。加 --allow-partial-cache 則沿用交集、
    只補算新增條目——僅在既有條目的 title/content 未被改動時才成立,
    因此務必搭配 --verify-sample 抽驗。
    """
    if not path.exists():
        return None
    cached = json.loads(path.read_text(encoding="utf-8"))
    if cached.get("provider") != REQUIRED_PROVIDER:
        print(f"[warn] 快取 provider 是 {cached.get('provider')}，不是 "
              f"{REQUIRED_PROVIDER}，忽略（Fake 向量不可落地）。")
        return None

    cmap = dict(zip(cached.get("ids", []), cached.get("vectors", [])))
    if list(cached.get("ids", [])) == ids:
        return cmap

    missing = [i for i in ids if i not in cmap]
    extra = [i for i in cmap if i not in set(ids)]
    print(f"[cache] 快取 {len(cmap)} 條 vs 種子檔 {len(ids)} 條")
    print(f"        缺少（需補算）：{missing if len(missing) <= 10 else missing[:10] + ['…']}")
    print(f"        多餘（KB 已移除）：{extra if len(extra) <= 10 else extra[:10] + ['…']}")
    if not allow_partial:
        print("[warn] id 集合不一致，整包忽略快取。"
              "若確定既有條目文字未變，可加 --allow-partial-cache 只補算缺少的。")
        return None
    print(f"[cache] 沿用交集 {len(ids) - len(missing)} 條，補算 {len(missing)} 條")
    return {i: cmap[i] for i in ids if i in cmap}


def verify_cache_sample(entries: dict[str, KBEntry], cached: dict[str, list[float]],
                        emb, n: int) -> list[str]:
    """抽驗:重算 n 條「快取內既有」條目,與快取值比餘弦相似度。

    這一步同時擋掉兩種漂移:既有條目文字被改過、以及模型/tokenizer 版本不同。
    快取存的是 round(x, 6),所以比相似度而非比相等。
    """
    if n <= 0 or not cached:
        return []
    picks = sorted(cached)[:: max(1, len(cached) // n)][:n]
    docs = [f"{entries[i].title}\n{entries[i].content}" for i in picks]
    fresh = emb.embed(docs)
    lines = []
    for i, v in zip(picks, fresh):
        c = cached[i]
        sim = sum(a * b for a, b in zip(v, c))
        sim /= ((sum(x * x for x in v) ** 0.5) * (sum(x * x for x in c) ** 0.5)) or 1.0
        ok = sim >= 0.9999
        lines.append(f"{i} sim={sim:.6f} {'OK' if ok else 'FAIL'}")
        if not ok:
            sys.exit(f"抽驗失敗：{i} 的重算向量與快取不符（sim={sim:.6f}）。"
                     "既有條目文字或模型版本已變動，請改跑 "
                     "build_kb_index.py --real --rebuild 全量重建。")
    return lines


def embed_entries(entries: dict[str, KBEntry], ids: list[str],
                  known: dict[str, list[float]] | None = None,
                  verify_sample: int = 0,
                  cache_path: Path | None = None) -> tuple[dict[str, list[float]], list[str]]:
    known = dict(known or {})
    todo = [i for i in ids if i not in known]
    if not todo:
        return known, []
    est = "10–40 分鐘" if len(todo) > 100 else "數十秒"
    print(f"[embed] 需計算 {len(todo)} 條向量（bge-m3，CPU 約 {est}）", flush=True)
    from app.providers.embeddings import BgeM3Embedding
    emb = BgeM3Embedding()
    checks = verify_cache_sample(entries, known, emb, verify_sample)
    for line in checks:
        print(f"[verify] {line}")
    docs = [f"{entries[i].title}\n{entries[i].content}" for i in todo]
    vecs: list[list[float]] = []
    for s in range(0, len(docs), 128):
        vecs.extend(emb.embed(docs[s:s + 128]))
    known.update(zip(todo, vecs))
    if cache_path:
        write_cache(cache_path, ids, known)
    return known, checks


def write_cache(path: Path, ids: list[str], vectors: dict[str, list[float]]) -> None:
    """回寫快取,格式與 build_kb_index.py／VectorRetriever 完全一致。

    不回寫的話,每次重跑都要為了那幾條新條目把 2.3GB 模型載進記憶體;
    寫回去之後全庫命中,下游(含 run_golden_pairs.py --real)也一併受惠。
    """
    if any(i not in vectors for i in ids):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(
        provider=REQUIRED_PROVIDER, ids=ids,
        vectors=[[round(x, 6) for x in vectors[i]] for i in ids])),
        encoding="utf-8")
    print(f"[cache] 已回寫 {len(ids)} 條到 {path}（下次重跑不需要模型）")


def to_atlas_doc(e: KBEntry, vec: list[float]) -> dict:
    return {
        "_id": e.id,
        "type": e.type,
        "title": e.title,
        "text": e.content,                       # 合約:內部 content → 落地 text
        "skills": e.skills,
        "source": e.metadata.get("source", ""),  # 提到頂層
        "metadata": e.metadata,                  # 整包保留,filter 走 metadata.industry
        "embedding": vec,
        "embeddingModel": "bge-m3",
        "embeddingDim": EMBEDDING_DIM,
    }


# --------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default=None, help="不建議：優先用 .env 的 MONGODB_URI")
    ap.add_argument("--db", default=os.getenv("MONGODB_DB", ""),
                    help="目標 database（需先向資料庫組確認）")
    ap.add_argument("--collection", default=DEFAULT_COLLECTION)
    ap.add_argument("--vectors", type=Path, default=DEFAULT_VECTOR_CACHE)
    ap.add_argument("--allow-partial-cache", action="store_true",
                    help="快取 id 不吻合時,沿用交集只補算新增條目")
    ap.add_argument("--verify-sample", type=int, default=3,
                    help="用部分快取時抽驗幾條既有向量（0=不驗）")
    ap.add_argument("--create-index", action="store_true")
    ap.add_argument("--smoke", default=None, help="落地後跑一次 $vectorSearch")
    ap.add_argument("--smoke-type", default=None, help="煙霧測試加 type filter")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--check", action="store_true",
                    help="只驗連線與目標 DB 現況,不寫入任何資料")
    ap.add_argument("--dry-run", action="store_true", help="只驗資料,不連線")
    ap.add_argument("--print-index-json", action="store_true",
                    help="印出索引定義供 Atlas UI 貼上,不做其他事")
    ap.add_argument("--report", type=Path, default=None,
                    help="寫驗收紀錄（已遮蔽 URI，可提交 Git）")
    args = ap.parse_args()

    index_def = json.loads(INDEX_DEF_PATH.read_text(encoding="utf-8"))
    if args.print_index_json:
        print(json.dumps(index_def["definition"], ensure_ascii=False, indent=2))
        return

    # 0. 前置檢查 ---------------------------------------------------
    # 先驗連線參數再算向量:算向量可能要 40 分鐘,不該跑完才發現 db 沒填。
    uri = ""
    if not args.dry_run:
        uri = resolve_uri(args.uri)
        args.db = resolve_db(args.db, uri)
    if args.check:
        run_check(uri, args.db, args.collection, index_def["name"])
        return

    # 1. 資料 -------------------------------------------------------
    entries = load_entries()
    ids = sorted(entries)
    print(f"[data] 種子檔共 {len(ids)} 條")
    for t in sorted({e.type for e in entries.values()}):
        print(f"       {t}: {sum(1 for e in entries.values() if e.type == t)}")

    vectors = load_cached_vectors(args.vectors, ids, args.allow_partial_cache)
    checks: list[str] = []
    cache_hit = len(vectors or {})
    if not args.dry_run and (vectors is None or len(vectors) < len(ids)):
        vectors, checks = embed_entries(entries, ids, vectors,
                                        args.verify_sample if vectors else 0,
                                        cache_path=args.vectors)
    if vectors:
        missing = [i for i in ids if i not in vectors]
        bad = [i for i in ids if i in vectors and len(vectors[i]) != EMBEDDING_DIM]
        if bad:
            sys.exit(f"維度不符 {EMBEDDING_DIM}（合約變更）：{bad[:3]}")
        if missing and not args.dry_run:
            sys.exit(f"向量缺漏：{missing[:3]}")
        print(f"[data] 向量就緒 {len(vectors)} 條 × {EMBEDDING_DIM} 維"
              f"（快取 {cache_hit}／新算 {len(vectors) - cache_hit}）"
              + (f"；dry-run 未計算 {len(missing)} 條" if missing else ""))

    if args.dry_run:
        print("[dry-run] 未連線。預計寫入 "
              f"{len(ids)} 條到 {args.db or '<db>'}.{args.collection}")
        return

    # 2. 連線與寫入 -------------------------------------------------
    from pymongo import UpdateOne

    client = make_client(uri, "career-sandbox-ingest")
    client.admin.command("ping")
    print(f"[atlas] 已連線 {mask_uri(uri)} → {args.db}.{args.collection}")

    coll = client[args.db][args.collection]
    before = coll.estimated_document_count()

    now = datetime.now(timezone.utc)
    ops = [UpdateOne({"_id": i},
                     {"$set": {**to_atlas_doc(entries[i], vectors[i]),
                               "updatedAt": now},
                      "$setOnInsert": {"createdAt": now}},
                     upsert=True)
           for i in ids]
    t0 = time.time()
    res = coll.bulk_write(ops, ordered=False)
    after = coll.count_documents({})
    print(f"[atlas] upsert 完成（{time.time() - t0:.1f}s）："
          f"新增 {res.upserted_count}／更新 {res.modified_count}")
    print(f"[atlas] 文件數 {before} → {after}（種子檔 {len(ids)}）")
    if after != len(ids):
        print(f"[warn] collection 文件數 {after} ≠ 種子檔 {len(ids)}，"
              "可能有前次殘留或他人寫入，請人工確認再簽驗收。")

    # 3. 索引 -------------------------------------------------------
    index_name = index_def["name"]
    index_state = "skipped"
    if args.create_index:
        from pymongo.operations import SearchIndexModel
        existing = {ix["name"] for ix in coll.list_search_indexes()}
        if index_name in existing:
            print(f"[index] {index_name} 已存在，不重建")
            index_state = "existing"
        else:
            coll.create_search_index(
                model=SearchIndexModel(definition=index_def["definition"],
                                       name=index_name, type="vectorSearch"))
            print(f"[index] 已送出 {index_name}，等待 queryable……", flush=True)
            for _ in range(60):
                ix = next(iter(coll.list_search_indexes(index_name)), None)
                if ix and ix.get("queryable"):
                    index_state = "ready"
                    break
                time.sleep(5)
            print(f"[index] 狀態：{index_state}"
                  if index_state == "ready"
                  else "[index] 逾時未 queryable，請到 Atlas UI 確認建置進度")

    # 4. 煙霧測試 ---------------------------------------------------
    smoke_lines: list[str] = []
    if args.smoke:
        from app.providers.embeddings import BgeM3Embedding
        qv = BgeM3Embedding(verbose=False).embed([args.smoke])[0]
        stage = {"index": index_name, "path": "embedding", "queryVector": qv,
                 "numCandidates": max(100, args.k * 20), "limit": args.k}
        if args.smoke_type:
            stage["filter"] = {"type": args.smoke_type}
        hits = list(coll.aggregate([
            {"$vectorSearch": stage},
            {"$project": {"_id": 1, "type": 1, "title": 1,
                          "score": {"$meta": "vectorSearchScore"}}}]))
        print(f"\n[smoke] 查詢：{args.smoke}")
        for h in hits:
            line = f"  {h['score']:.3f}  [{h['_id']}] ({h['type']}) {h['title'][:40]}"
            print(line)
            smoke_lines.append(line.strip())
        if not hits:
            print("  （無結果：索引可能尚未 queryable，或 filter 過嚴）")

    # 5. 驗收紀錄 ---------------------------------------------------
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join([
            "# Atlas 落地驗收紀錄", "",
            f"- 執行時間：{now.isoformat()}",
            f"- 連線：`{mask_uri(uri)}`",
            f"- 目標：`{args.db}.{args.collection}`",
            f"- 種子檔條數：{len(ids)}",
            f"- 落地後文件數：{after}",
            f"- 新增／更新：{res.upserted_count}／{res.modified_count}",
            f"- 向量：bge-m3，{EMBEDDING_DIM} 維"
            f"（快取沿用 {cache_hit}／新計算 {len(ids) - cache_hit}）",
            f"- 快取抽驗：{'；'.join(checks) if checks else '未執行（全量快取或全量重算）'}",
            f"- 索引：`{index_name}`（{index_state}）", "",
            "## Smoke query", "",
            f"查詢：{args.smoke or '(未執行)'}", "",
            *[f"- {l}" for l in smoke_lines], "",
            "> 本檔不含任何連線字串或帳密。",
        ]) + "\n", encoding="utf-8")
        print(f"\n[report] 已寫出 {args.report}（不含 URI，可提交）")

    client.close()


if __name__ == "__main__":
    main()
