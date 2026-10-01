"""매일 뉴스를 모아 요약해서 news.json에 저장합니다. (파이썬 기본 기능만 사용)"""
import json, os, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
MODEL = "claude-haiku-4-5-20251001"
KEEP_DAYS = 14
PER_CAT = 6

# 카테고리별 검색어. 여기를 고치면 수집 범위가 바뀝니다.
QUERIES = {
    "tire": "타이어 OR 한국타이어 OR 금호타이어 OR 넥센타이어 when:1d",
    "car": "완성차 OR 자동차 판매 OR 현대차 OR 기아 when:1d",
    "part": "자동차 부품 OR 자동차 부품업계 when:1d",
    "ev": "전기차 OR 배터리 자동차 when:1d",
    "trade": "자동차 관세 OR 타이어 관세 OR 반덤핑 타이어 when:2d",
}


def fetch_rss(cat, query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    items = []
    for it in root.iter("item"):
        src = it.find("source")
        ts = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        items.append({"c": cat, "h": it.findtext("title"), "url": it.findtext("link"),
                      "src": src.text if src is not None else "", "ts": ts.strftime("%Y-%m-%dT%H:%M")})
    return items[:PER_CAT]


def summarize(items):
    """제목만 보고 요약합니다. 제목에 없는 사실은 쓰지 않도록 지시합니다."""
    payload = [{"id": i, "category": n["c"], "title": n["h"], "source": n["src"]} for i, n in enumerate(items)]
    prompt = (
        "다음은 자동차·타이어 업계 뉴스 제목 목록입니다. 각 항목에 대해 JSON 배열만 출력하세요.\n"
        '형식: [{"id":0,"keep":true,"s":"한국어 1~2문장 요약","p":"업계 포인트 한 줄"}]\n'
        "규칙: (1) 제목에 없는 사실, 숫자, 원인은 절대 추가하지 마세요. 제목만으로 알 수 없으면 s는 제목을 쉬운 말로 풀어쓰기만 하세요. "
        "(2) p는 이 소식이 타이어·자동차 업계에서 갖는 의미를 조심스럽게 한 줄로 쓰되, 확정적 단정은 피하세요. "
        "(3) 자동차·타이어 업계와 무관하거나 광고성이면 keep을 false로 하세요.\n\n"
        + json.dumps(payload, ensure_ascii=False))
    body = json.dumps({"model": MODEL, "max_tokens": 6000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    text = json.loads(urllib.request.urlopen(req, timeout=120).read())["content"][0]["text"]
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return {r["id"]: r for r in json.loads(text)}


def main():
    old = json.load(open("news.json", encoding="utf-8")) if os.path.exists("news.json") else []
    seen = {n["url"] for n in old}
    fresh, titles = [], set()
    for cat, q in QUERIES.items():
        try:
            for n in fetch_rss(cat, q):
                if n["url"] not in seen and n["h"] not in titles:
                    titles.add(n["h"]); fresh.append(n)
        except Exception as e:
            print("수집 실패:", cat, e)
    if fresh:
        try:
            res = summarize(fresh)
            for i, n in enumerate(fresh):
                r = res.get(i)
                if r and r.get("keep"):
                    n["s"], n["p"] = r["s"], r["p"]
                    old.append(n)
        except Exception as e:
            print("요약 실패:", e)
    cutoff = (datetime.now(KST) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M")
    old = sorted([n for n in old if n["ts"] >= cutoff], key=lambda n: n["ts"], reverse=True)
    json.dump(old, open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장된 뉴스:", len(old), "건 / 새로 추가:", len(fresh), "건 후보")


main()
