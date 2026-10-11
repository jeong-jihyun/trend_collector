#!/usr/bin/env python3
"""
요즘 트렌드 수집기 (추가 설치 없이 파이썬만 있으면 실행됩니다)

수집 대상
  1) 구글 트렌드 (한국 급상승 검색어)
  2) GeekNews (한국 개발자 뉴스)
  3) Hacker News (해외 개발/IT 인기글)
  4) GitHub (최근 7일 내 뜨는 저장소)
  5) Product Hunt (새로 나온 제품/서비스)

실행:  python trend_collector.py
결과:  trends/trends_YYYY-MM-DD.md  (읽기용 보고서)
       trends/trends_YYYY-MM-DD.json (다른 프로그램에서 쓰기용)
"""

import json
import re
import datetime as dt
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0 (trend-collector/1.0)"}
OUT_DIR = Path("trends")
TOP_N = 15  # 소스별로 가져올 개수


# ---------- 공통 도구 ----------
def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def local(tag):
    """XML 태그에서 {네임스페이스} 부분을 떼어냅니다."""
    return tag.split("}")[-1]


def parse_feed(xml_bytes, limit=TOP_N):
    """RSS / Atom 둘 다 읽어서 [{title, link, extra}] 로 돌려줍니다."""
    root = ET.fromstring(xml_bytes)
    items = []
    for node in root.iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        title, link, extra = "", "", ""
        for child in node:
            name = local(child.tag)
            if name == "title":
                title = (child.text or "").strip()
            elif name == "link":
                link = child.attrib.get("href") or (child.text or "").strip()
            elif name == "approx_traffic":  # 구글 트렌드 검색량
                extra = (child.text or "").strip()
        if title:
            items.append({"title": title, "link": link, "extra": extra})
        if len(items) >= limit:
            break
    return items


# ---------- 소스별 수집 함수 ----------
def google_trends_kr():
    xml = fetch("https://trends.google.com/trending/rss?geo=KR")
    items = parse_feed(xml)
    for it in items:
        it["link"] = "https://www.google.com/search?q=" + urllib.parse.quote(it["title"])
        if it["extra"]:
            it["extra"] = f"검색 {it['extra']}"
    return items


def geeknews():
    return parse_feed(fetch("https://news.hada.io/rss/news"))


def hacker_news():
    ids = json.loads(fetch("https://hacker-news.firebaseio.com/v0/topstories.json"))[:TOP_N]

    def get(i):
        d = json.loads(fetch(f"https://hacker-news.firebaseio.com/v0/item/{i}.json"))
        return {
            "title": d.get("title", ""),
            "link": d.get("url") or f"https://news.ycombinator.com/item?id={i}",
            "extra": f"👍{d.get('score', 0)} 💬{d.get('descendants', 0)}",
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(get, ids))


def github_rising():
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    q = urllib.parse.quote(f"created:>{since}")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={TOP_N}"
    data = json.loads(fetch(url))
    return [
        {
            "title": f"{r['full_name']} - {(r.get('description') or '')[:80]}",
            "link": r["html_url"],
            "extra": f"⭐{r['stargazers_count']}",
        }
        for r in data.get("items", [])
    ]


def product_hunt():
    return parse_feed(fetch("https://www.producthunt.com/feed"))


SOURCES = {
    "🔥 구글 트렌드 (한국)": google_trends_kr,
    "🇰🇷 GeekNews": geeknews,
    "🌍 Hacker News": hacker_news,
    "💻 GitHub 급상승": github_rising,
    "🚀 Product Hunt": product_hunt,
}


# ---------- 키워드 뽑기 ----------
STOP = set("""the and for with that this from your you are how what why not but can
will new use using via into about out all has have more than just get make
있는 하는 대한 위한 어떻게 그리고 에서 으로 하기 합니다 입니다 및 등 수 것 더""".split())


def hot_keywords(all_titles, top=15):
    words = []
    for t in all_titles:
        for w in re.findall(r"[A-Za-z가-힣0-9+#.]{2,}", t):
            w = w.lower().strip(".")
            if w and w not in STOP and not w.isdigit():
                words.append(w)
    return Counter(words).most_common(top)


# ---------- 메인 ----------
def main():
    today = dt.date.today().isoformat()
    results = {}

    for name, fn in SOURCES.items():
        try:
            results[name] = fn()
            print(f"[OK]   {name}: {len(results[name])}건")
        except Exception as e:  # 한 곳이 실패해도 나머지는 계속
            results[name] = []
            print(f"[FAIL] {name}: {e}")

    titles = [it["title"] for items in results.values() for it in items]
    keywords = hot_keywords(titles)

    OUT_DIR.mkdir(exist_ok=True)

    lines = [f"# 📈 오늘의 트렌드 ({today})", ""]
    lines.append("## 🔑 여러 곳에서 자주 나온 키워드")
    lines.append(", ".join(f"**{w}**({c})" for w, c in keywords) or "- 없음")
    lines.append("")
    for name, items in results.items():
        lines.append(f"## {name}")
        if not items:
            lines.append("- (수집 실패 또는 데이터 없음)")
        for i, it in enumerate(items, 1):
            extra = f" `{it['extra']}`" if it["extra"] else ""
            lines.append(f"{i}. [{it['title']}]({it['link']}){extra}")
        lines.append("")

    md_path = OUT_DIR / f"trends_{today}.md"
    json_path = OUT_DIR / f"trends_{today}.json"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(
        json.dumps({"date": today, "keywords": keywords, "sources": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n저장 완료 → {md_path}")


if __name__ == "__main__":
    main()
