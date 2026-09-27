#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教育ネタ 自動収集スクリプト（無料・API不要・課金不要）
週に1回 GitHub Actions から実行され、教育関係の最新ニュースを
「信頼できる媒体だけ」から集めて ideas.csv に貯め、
weekly.md に「直近1週間のネタ候補」をまとめます。

weekly.md は毎週月曜の朝、Claude（スケジュール実行）が読み込んで
要約・切り口つきの一覧にして、スマホに通知します。

2026-09 改修
- 情報源を「許可した媒体（全国紙・NHK・通信社・教育専門紙・官公庁）」だけに限定
- Googleニュース検索（直近7日）＋はてブ検索の二本立て
- 同じニュースの転載は1本にまとめる
- weekly.md は「直近7日に集めた分すべて」を表示（途中で何回実行しても欠けない）
"""

import csv
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# ============================================================
# ★ここから下の設定だけ書き換えればOK
# ============================================================

# 1) 調べるテーマ（Googleニュースで直近7日を検索します）
QUERIES = [
    "不登校",
    "発達障害 子ども",
    "特別支援教育",
    "いじめ 学校",
    "小学校 教員",
    "中学校 保護者",
    "子育て 学校",
    "文部科学省 学校",
    "こども家庭庁",
]

# 2) はてなブックマークの検索（話題になっている記事を拾う補助）
HATENA_QUERIES = ["不登校", "発達障害", "教員"]

# 3) 記事を採用してよい媒体（ドメインの末尾で判定）
#    ここに無い媒体の記事は、どんなに話題でも拾いません。
ALLOW_DOMAINS = {
    # 公共放送・通信社
    "nhk.or.jp": "NHK", "web.nhk": "NHK",
    "kyodonews.jp": "共同通信", "47news.jp": "共同通信（47NEWS）",
    "jiji.com": "時事通信",
    # 全国紙
    "asahi.com": "朝日新聞", "yomiuri.co.jp": "読売新聞",
    "mainichi.jp": "毎日新聞", "nikkei.com": "日本経済新聞",
    "sankei.com": "産経新聞", "tokyo-np.co.jp": "東京新聞",
    # 主な地方紙
    "chunichi.co.jp": "中日新聞", "nishinippon.co.jp": "西日本新聞",
    "hokkaido-np.co.jp": "北海道新聞", "kobe-np.co.jp": "神戸新聞",
    "kyoto-np.co.jp": "京都新聞",
    # 教育の専門媒体
    "kyobun.co.jp": "教育新聞", "resemom.jp": "リセマム",
    "toyokeizai.net": "東洋経済オンライン",
    # 官公庁（一次情報）
    "mext.go.jp": "文部科学省", "cfa.go.jp": "こども家庭庁",
    "mhlw.go.jp": "厚生労働省",
}

MAX_PER_QUERY = 4   # 1つのテーマから拾う最大件数（偏り防止）
MAX_PER_RUN = 25    # 1回で拾う最大件数
MAX_AGE_DAYS = 8    # これより古い記事は拾わない
# ============================================================

CSV_FILE = "ideas.csv"
DIGEST_FILE = "weekly.md"
HEADERS = ["収集日", "タイトル", "URL", "メモ", "ステータス", "媒体", "公開日"]

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y-%m-%d")
UA = {"User-Agent": "Mozilla/5.0 (topic-collector)"}


def localname(tag):
    return tag.rsplit("}", 1)[-1]


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=JST)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except Exception:
        return None


def media_name(url):
    """URLが許可した媒体なら媒体名、そうでなければ空文字"""
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    for domain, name in ALLOW_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return ""


def fetch_feed(url):
    """RSSを読み込み、記事の辞書のリストを返す"""
    items = []
    safe_url = urllib.parse.quote(url, safe=":/?&=%")
    try:
        req = urllib.request.Request(safe_url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            root = ET.fromstring(resp.read())
    except Exception as e:
        print(f"取得失敗 {url}: {e}")
        return items
    for el in root.iter():
        if localname(el.tag) != "item":
            continue
        it = {"title": "", "link": "", "desc": "", "date": None, "site": ""}
        for child in el:
            name = localname(child.tag)
            text = (child.text or "").strip()
            if name == "title":
                it["title"] = text
            elif name == "link":
                it["link"] = text
            elif name == "description":
                it["desc"] = text
            elif name in ("date", "pubDate"):
                it["date"] = parse_date(text)
            elif name == "source":   # Googleニュースは元の媒体URLをここに持っている
                it["site"] = child.attrib.get("url", "")
        if it["title"] and it["link"]:
            items.append(it)
    print(f"{len(items)}件 読み込み: {url}")
    return items


def google_news(query):
    q = urllib.parse.quote(f"{query} when:7d")
    return f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"


def hatena(query):
    return f"https://b.hatena.ne.jp/q/{query}?target=text&sort=recent&mode=rss"


def title_key(title):
    """「記事名 - 媒体名」の媒体名や記号を外して比べる（同じニュースの転載をまとめる）"""
    t = title.rsplit(" - ", 1)[0]
    t = re.sub(r"[｜|].*$", "", t)
    return re.sub(r"[\s　「」『』【】（）()、。・:：!！?？]", "", t)[:40]


def clean(text):
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()[:120]


def load_rows():
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    rows = load_rows()
    seen = {r["URL"] for r in rows} | {title_key(r["タイトル"]) for r in rows}

    sources = [(q, google_news(q)) for q in QUERIES] + \
              [(f"はてブ:{q}", hatena(q)) for q in HATENA_QUERIES]

    new_items = []
    for label, url in sources:
        taken = 0
        for it in fetch_feed(url):
            if taken >= MAX_PER_QUERY or len(new_items) >= MAX_PER_RUN:
                break
            # Googleニュースは <source url> で、はてブは記事URLそのもので媒体を判定
            media = media_name(it["site"] or it["link"])
            if not media:
                continue
            if it["date"] and NOW - it["date"] > timedelta(days=MAX_AGE_DAYS):
                continue
            tk = title_key(it["title"])
            if it["link"] in seen or tk in seen:
                continue
            seen.update([it["link"], tk])
            it["media"] = media
            it["desc"] = clean(it["desc"]) if it["desc"] and "<a " not in it["desc"] else ""
            new_items.append(it)
            taken += 1

    # CSVに追記（古い形式のファイルなら見出し行だけ新しい形に置き換える）
    if rows and len(rows[0]) < len(HEADERS):
        with open(CSV_FILE, encoding="utf-8") as f:
            body = f.read().split("\n", 1)[1]
        with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(HEADERS) + "\n" + body)
    new_file = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(HEADERS)
        for it in new_items:
            pub = it["date"].astimezone(JST).strftime("%Y-%m-%d") if it["date"] else ""
            writer.writerow([TODAY, it["title"], it["link"], it["desc"], "未確認",
                             it["media"], pub])

    # weekly.md：直近7日に集めた分をすべて載せる
    since = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [r for r in load_rows() if r["収集日"] > since and r.get("媒体")]
    lines = [f"# 今週の教育ニュース候補（{TODAY} 更新）\n",
             f"信頼できる媒体（全国紙・NHK・通信社・教育専門紙・官公庁）の直近1週間の記事 {len(recent)} 件。\n"]
    for i, r in enumerate(recent, 1):
        lines.append(f"## {i}. {r['タイトル']}")
        lines.append(f"媒体：{r['媒体']}　公開日：{r.get('公開日') or '不明'}")
        if r.get("メモ"):
            lines.append(r["メモ"])
        lines.append(f"{r['URL']}\n")
    if not recent:
        lines.append("今週は条件に合う記事が見つかりませんでした。")
    with open(DIGEST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"{len(new_items)}件を追加しました。weekly.md は {len(recent)} 件です。")


if __name__ == "__main__":
    main()
