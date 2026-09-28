#!/usr/bin/env python3
"""Geocode pins.json via 国土地理院 address search and emit map.html (Leaflet) + mymaps.csv."""
import json, re, csv, time, unicodedata, urllib.parse, urllib.request, os, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
PINS = os.path.join(HERE, "pins.json")
CACHE = os.path.join(HERE, "geocache.json")
OUT_HTML = os.path.join(HERE, "map.html")
OUT_CSV = os.path.join(HERE, "mymaps.csv")

# ---- category bucketing (order matters: first match wins) ----
CATEGORIES = [
    ("飲食 (和食・そば・寿司)", ["寿司", "鮨", "そば", "蕎麦", "うどん", "うなぎ", "和食", "日本料理", "割烹", "小料理", "天ぷら", "とんかつ", "おでん", "串揚げ", "鉄板", "お好み焼", "たこ焼", "魚", "定食", "鍋", "ちゃんこ", "かに", "鶏料理", "沖縄", "軽食"]),
    ("飲食 (居酒屋・バー・スナック)", ["居酒屋", "バー", "BAR", "Bar", "スナック", "麻雀", "酒菜", "ビストロ", "焼鳥", "焼き鳥", "日本酒", "もつ焼", "焼きとん", "パブ", "ワイン"]),
    ("飲食 (中華・アジア・カレー)", ["中華", "ラーメン", "餃子", "韓国", "台湾", "インド", "カレー", "タイ", "アジア", "タコス", "オカアチャン"]),
    ("飲食 (洋食・焼肉・その他)", ["イタリア", "フレンチ", "フランス", "ピザ", "レストラン", "焼肉", "焼き肉", "肉料理", "飲食", "食堂", "ダイニング", "Dining", "シェアキッチン", "ハンバーグ", "洋食", "ステーキ", "スペイン", "イタリヤ", "シャルキュトリ"]),
    ("カフェ・パン・スイーツ", ["カフェ", "喫茶", "コーヒー", "珈琲", "豆焙煎", "パン", "ベーカリー", "菓子", "スイーツ", "ケーキ", "カステラ", "サンドイッチ", "饅頭", "まんじゅう", "飴", "ナッツ", "茶", "クレープ", "煎餅", "CAF", "caf", "Caf"]),
    ("食料品・スーパー・コンビニ", ["スーパー", "コンビニ", "食料品", "精肉", "鳥肉", "青果", "八百屋", "米", "豆腐", "惣菜", "弁当", "酒", "ハム", "自然食", "食品", "物販", "フードセンター", "ディスカウント", "調味料", "海苔", "乾物", "生鮮", "肉", "卸"]),
    ("美容・理容", ["美容", "理容", "ヘア", "エステ", "ネイル", "床屋", "理髪", "アイラッシュ", "ビューティー", "サロン"]),
    ("薬局・医療・整体", ["薬局", "ドラッグ", "整体", "整骨", "鍼灸", "マッサージ", "治療", "歯科", "医院", "内科", "皮膚科", "クリニック", "接骨", "カイロ", "ドラック", "医薬品", "漢方", "動物病院", "ジム", "ピラティス"]),
    ("生花・雑貨・衣料・書籍", ["生花", "花", "フラワー", "雑貨", "民芸", "インテリア", "家具", "ギャラリー", "婦人服", "アパレル", "衣料", "呉服", "服", "アクセサリー", "宝石", "貴金属", "時計", "メガネ", "眼鏡", "手芸", "書", "文具", "レコード", "楽器", "化粧品", "リサイクル", "古書", "玩具", "靴", "バッグ", "バック", "小物", "ブティック", "ファッション", "セレクトショップ", "洋品", "寝具", "文房具", "古本", "美術", "額装", "ガラス", "スポーツ", "オーディオ", "ペット", "音楽"]),
    ("暮らし・サービス (修理・不動産 等)", ["クリーニング", "修理", "自転車", "サイクル", "バイク", "自動車", "板金", "家電", "電気", "電化", "ガス", "金物", "鍵", "畳", "建材", "木材", "不動産", "葬儀", "新聞", "コピー", "製本", "塾", "学校", "教室", "保育", "ガソリン", "携帯", "写真", "印刷", "保険", "工事", "リフォーム", "はんこ", "プリント", "フォト", "工務店", "襖", "内装", "葬祭", "映像", "サービス業"]),
]

def categorize(t: str) -> str:
    for cat, kws in CATEGORIES:
        for kw in kws:
            if kw in t:
                return cat
    return "その他"

PALETTE = {
    "飲食 (和食・そば・寿司)": "#d62728",
    "飲食 (居酒屋・バー・スナック)": "#9467bd",
    "飲食 (中華・アジア・カレー)": "#ff7f0e",
    "飲食 (洋食・焼肉・その他)": "#e377c2",
    "カフェ・パン・スイーツ": "#bcbd22",
    "食料品・スーパー・コンビニ": "#2ca02c",
    "美容・理容": "#17becf",
    "薬局・医療・整体": "#1f77b4",
    "生花・雑貨・衣料・書籍": "#8c564b",
    "暮らし・サービス (修理・不動産 等)": "#7f7f7f",
    "その他": "#000000",
}

# ---- address normalisation ----
def norm_street(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("−", "-").replace("ー", "-").replace("―", "-").replace("‐", "-").replace("－", "-")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(\d+)丁目\s*", r"\1-", s)   # 1丁目2-22 -> 1-2-22
    s = re.sub(r"(\d+)番地?\s*", r"\1-", s)
    s = re.sub(r"(\d+)号", r"\1", s)
    s = s.replace("--", "-").rstrip("-")
    # cut anything after the numeric part (building names, floors)
    m = re.match(r"^([^\d]+?\d+(?:-\d+){0,2})", s)
    return m.group(1) if m else s

FIXES = {"天寺2-14-10": ("目黒区", "祐天寺2-14-10"), "小山7-15-21": ("品川区", "小山7-15-21")}

def candidates(ward: str, street: str):
    base = norm_street(street)
    if base in FIXES:
        ward, base = FIXES[base]
    yield f"東京都{ward}{base}"
    parts = base.rsplit("-", 1)
    if len(parts) == 2 and "-" in parts[0]:
        yield f"東京都{ward}{parts[0]}"   # drop 号 -> 番 level
    parts2 = base.split("-", 1)
    yield f"東京都{ward}{parts2[0]}"       # 丁目 level

def gsi(q: str):
    url = "https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(q)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.load(r)
            if data:
                lon, lat = data[0]["geometry"]["coordinates"]
                return lat, lon, data[0]["properties"].get("title", "")
            return None
        except Exception as e:
            time.sleep(1 + attempt)
    return None

def geocode(item, cache):
    key = f"{item['ward']}|{item['street']}"
    if key in cache:
        return cache[key]
    result = None
    for level, q in enumerate(candidates(item["ward"], item["street"])):
        r = gsi(q)
        if r:
            t = r[2]
            prec = 0 if "号" in t else 1 if "番" in t else 2 if "丁目" in t else 3
            result = {"lat": r[0], "lon": r[1], "matched": t, "query": q, "precision": prec}
            break
        time.sleep(0.2)
    cache[key] = result
    return result

def main():
    pins = json.load(open(PINS, encoding="utf-8"))
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    todo = [p for p in pins if f"{p['ward']}|{p['street']}" not in cache]
    print(f"{len(pins)} pins, {len(todo)} to geocode", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, _ in enumerate(ex.map(lambda p: geocode(p, cache), todo), 1):
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}", file=sys.stderr)
                json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    feats = []
    missing = []
    for p in pins:
        g = cache.get(f"{p['ward']}|{p['street']}")
        cat = categorize(p["type"])
        if not g:
            missing.append(p)
            continue
        feats.append({**p, "lat": g["lat"], "lon": g["lon"], "cat": cat, "precision": g["precision"]})

    from collections import Counter
    print("category counts:", Counter(f["cat"] for f in feats), file=sys.stderr)
    print("precision counts (0=号,1=番,2=丁目,3=区のみ):", Counter(f["precision"] for f in feats), file=sys.stderr)
    print("unmatched:", len(missing), [m["street"] for m in missing], file=sys.stderr)
    print("その他 types:", sorted({p['type'] for p in pins if categorize(p['type'])=='その他'}), file=sys.stderr)

    # ---- CSV for Google My Maps ----
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "category", "type", "address", "phone", "station", "area", "association", "lat", "lon"])
        for p in pins:
            g = cache.get(f"{p['ward']}|{p['street']}") or {}
            w.writerow([p["name"], categorize(p["type"]), p["type"], f"東京都{p['ward']}{p['street']}", p["phone"], p["station"], p["area"], p["association"], g.get("lat", ""), g.get("lon", "")])

    # ---- Leaflet HTML ----
    cats = [c for c, _ in CATEGORIES] + ["その他"]
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(feats, ensure_ascii=False)) \
                        .replace("__PALETTE__", json.dumps(PALETTE, ensure_ascii=False)) \
                        .replace("__CATS__", json.dumps(cats, ensure_ascii=False))
    open(OUT_HTML, "w", encoding="utf-8").write(html)
    print(f"wrote {OUT_HTML} ({len(feats)} pins) and {OUT_CSV}", file=sys.stderr)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>目黒区 商品券 取扱店マップ</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
html,body{height:100%;margin:0;font-family:system-ui,sans-serif}
#map{height:100%}
.legend{background:#fff;padding:8px 10px;border-radius:6px;box-shadow:0 1px 5px rgba(0,0,0,.4);font-size:13px;line-height:1.7;max-width:280px}
.legend label{display:flex;align-items:center;gap:6px;cursor:pointer;white-space:nowrap}
.legend .sw{width:12px;height:12px;border-radius:50%;border:1px solid #333;flex:none}
.legend .cnt{color:#777;margin-left:auto;padding-left:8px}
.legend .ctl{margin-top:6px;border-top:1px solid #ddd;padding-top:6px;font-size:12px}
.legend select{max-width:250px}
.leaflet-tooltip{font-size:12px;line-height:1.4}
</style></head><body>
<div id="map"></div>
<script>
const DATA=__DATA__, PALETTE=__PALETTE__, CATS=__CATS__;
const map=L.map('map');
const gsi=L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png',{maxZoom:18,attribution:'<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>'}).addTo(map);
const gsiStd=L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png',{maxZoom:18,attribution:'地理院タイル'});
const carto=L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap &copy; CARTO'});
L.control.layers({'地理院 淡色':gsi,'地理院 標準':gsiStd,'CARTO':carto},null,{position:'bottomleft'}).addTo(map);
const layers={}; CATS.forEach(c=>layers[c]=L.layerGroup().addTo(map));
const stations=[...new Set(DATA.map(d=>d.station))].sort();
const markers=[];
DATA.forEach(d=>{
  const m=L.circleMarker([d.lat,d.lon],{radius:6,color:'#222',weight:1,fillColor:PALETTE[d.cat],fillOpacity:.9});
  m.bindTooltip(`<b>${d.name}</b>${d.precision>=2?" <i>(住所あいまい)</i>":""}<br>${d.type}<br>${d.ward}${d.street}<br>${d.phone}<br>${d.station} / ${d.area}<br>${d.association}`,{sticky:true});
  m.bindPopup(`<b>${d.name}</b><br>${d.type}<br>${d.ward}${d.street}<br>${d.phone}<br>${d.station} / ${d.area}<br>${d.association}<br><a target="_blank" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(d.name+' 東京都'+d.ward+d.street)}">Google Mapsで開く</a>`);
  m._d=d; markers.push(m); layers[d.cat].addLayer(m);
});
map.fitBounds(L.featureGroup(markers).getBounds().pad(0.05));

const legend=L.control({position:'topright'});
legend.onAdd=()=>{
  const div=L.DomUtil.create('div','legend');
  L.DomEvent.disableClickPropagation(div); L.DomEvent.disableScrollPropagation(div);
  const counts={}; DATA.forEach(d=>counts[d.cat]=(counts[d.cat]||0)+1);
  div.innerHTML=CATS.map(c=>`<label><input type="checkbox" checked data-cat="${c}"><span class="sw" style="background:${PALETTE[c]}"></span>${c}<span class="cnt">${counts[c]||0}</span></label>`).join('')
   +`<div class="ctl"><a href="#" id="all">全て</a> / <a href="#" id="none">なし</a><br>駅: <select id="st"><option value="">全て</option>${stations.map(s=>`<option>${s}</option>`).join('')}</select></div>`;
  return div;
};
legend.addTo(map);
function applyStation(){
  const st=document.getElementById('st').value;
  markers.forEach(m=>{const ok=!st||m._d.station===st; if(ok){layers[m._d.cat].addLayer(m)}else{layers[m._d.cat].removeLayer(m)}});
}
document.querySelectorAll('.legend input[type=checkbox]').forEach(cb=>cb.addEventListener('change',e=>{
  const l=layers[e.target.dataset.cat]; e.target.checked?map.addLayer(l):map.removeLayer(l);
}));
document.getElementById('all').onclick=e=>{e.preventDefault();document.querySelectorAll('.legend input').forEach(cb=>{cb.checked=true;map.addLayer(layers[cb.dataset.cat])})};
document.getElementById('none').onclick=e=>{e.preventDefault();document.querySelectorAll('.legend input').forEach(cb=>{cb.checked=false;map.removeLayer(layers[cb.dataset.cat])})};
document.getElementById('st').onchange=applyStation;
</script></body></html>
"""

if __name__ == "__main__":
    main()
