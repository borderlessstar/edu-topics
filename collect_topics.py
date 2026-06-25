#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教育ネタ 自動収集スクリプト（無料・API不要・課金不要）
週に1回 GitHub Actions から実行され、教育関係で話題の記事を集めて
ideas.csv に貯め、weekly.md に「今週の動画ネタ候補」をまとめます。
"""

import csv
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ============================================================
# ★不登校・子育て・心理・カウンセリング・カウンセラー・小学校・中学校・学校
# ============================================================
# 集めてくる情報源（RSS）。行を足せば情報源を増やせます。
FEEDS = [
    "https://b.hatena.ne.jp/hotentry/social.rss",   # はてブ「世の中」（社会・教育問題）
    "https://b.hatena.ne.jp/hotentry/life.rss",      # はてブ「暮らし」（子育て・人間関係）
    "https://b.hatena.ne.jp/q/教育?target=text&sort=recent&mode=rss",   # 「教育」を含む新着
    "https://b.hatena.ne.jp/q/不登校?target=text&sort=recent&mode=rss", # 「不登校」を含む新着
    "https://b.hatena.ne.jp/q/教員?target=text&sort=recent&mode=rss",   # 「教員」を含む新着
]

# このどれかの言葉がタイトルか説明に入っている記事だけ拾う（[] にすると全部拾う）
KEYWORDS = ["教員", "先生", "教師", "学校", "教育現場", "担任", "不登校", "子育て",
            "発達", "保護者", "親子", "いじめ", "学級", "教育委員会", "ブラック"]
MAX_PER_WEEK = 15   # 1回で残す最大件数
# ============================================================

CSV_FILE = "ideas.csv"
DIGEST_FILE = "weekly.md"
HEADERS = ["収集日", "タイトル", "URL", "メモ", "ステータス"]

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
UA = {"User-Agent": "Mozilla/5.0 (topic-collector)"}


def localname(tag):
    """名前空間を外して要素名だけ取り出す"""
    return tag.rsplit("}", 1)[-1]


def fetch_feed(url):
    """RSSを読み込み、(タイトル, リンク, 説明) のリストを返す"""
    items = []
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"取得失敗 {url}: {e}")
        return items
    for el in root.iter():
        if localname(el.tag) != "item":
            continue
        title = link = desc = ""
        for child in el:
            name = localname(child.tag)
            if name == "title":
                title = (child.text or "").strip()
            elif name == "link":
                link = (child.text or "").strip()
            elif name == "description":
                desc = (child.text or "").strip()
        if title and link:
            items.append((title, link, desc))
    return items


def matches(title, desc):
    if not KEYWORDS:
        return True
    text = title + " " + desc
    return any(k in text for k in KEYWORDS)


def load_existing_urls():
    """すでに集めた記事URL（重複を避けるため）"""
    if not os.path.exists(CSV_FILE):
        return set()
    with open(CSV_FILE, encoding="utf-8") as f:
        return {row["URL"] for row in csv.DictReader(f)}


def clean(text):
    text = re.sub(r"<[^>]+>", "", text)        # HTMLタグを除去
    return re.sub(r"\s+", " ", text).strip()[:120]


def main():
    seen = load_existing_urls()
    new_items = []
    for url in FEEDS:
        for title, link, desc in fetch_feed(url):
            if link in seen or not matches(title, desc):
                continue
            seen.add(link)
            new_items.append((title, link, clean(desc)))
            if len(new_items) >= MAX_PER_WEEK:
                break
        if len(new_items) >= MAX_PER_WEEK:
            break

    # CSVに追記
    new_file = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(HEADERS)
        for title, link, desc in new_items:
            writer.writerow([TODAY, title, link, desc, "未確認"])

    # 今週のまとめを書き出す
    lines = [f"# 今週の動画ネタ候補（{TODAY}）\n",
             f"教育関係で話題になっている記事を {len(new_items)} 件集めました。\n"]
    for i, (title, link, desc) in enumerate(new_items, 1):
        lines.append(f"## {i}. {title}")
        if desc:
            lines.append(desc)
        lines.append(f"{link}\n")
    if not new_items:
        lines.append("今週は新しい記事が見つかりませんでした。")
    with open(DIGEST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"{len(new_items)}件を追加しました。")


if __name__ == "__main__":
    main()
