import streamlit as st
import streamlit.components.v1 as components
import json
import base64

st.set_page_config(layout="wide", page_title="WebGIS Palm River")
st.title("🗺️ WebGIS Dự án Palm City")

IMG_WIDTH = 3360
IMG_HEIGHT = 1800

IMAGE_PATH = "data/khuvuc_PalmCity.jpg"
ZONING_GEOJSON = "data/palm_zoning.geojson"
BUILDING_GEOJSON = "data/palm_building.geojson"


# ==========================================
# ĐỌC DỮ LIỆU (Python) — client-side JS chỉ nhận JSON đã xử lý sẵn
# ==========================================
def load_geojson(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def polygon_coords(feature):
    geom = feature["geometry"]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"][0][0]
    elif geom["type"] == "Polygon":
        return geom["coordinates"][0]
    return None


def to_svg_xy(px, py):
    """QGIS: x giữ nguyên, y âm tăng dần xuống dưới -> SVG (top-left, y dương xuống dưới): y_svg = -py"""
    return px, -py


def point_in_polygon(x, y, xs, ys):
    n = len(xs)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = xs[i], ys[i]
        xj, yj = xs[j], ys[j]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def find_label_point(xs, ys):
    """Tìm điểm ĐẶT NHÃN chắc chắn nằm bên trong polygon, gần tâm nhất.
    Tránh trường hợp centroid (trung bình đỉnh) rơi ra ngoài polygon lõm,
    khiến nhãn bị lấn sang khu vực khác."""
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    if point_in_polygon(cx, cy, xs, ys):
        return cx, cy

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    step_x = max((max_x - min_x) / 50, 1)
    step_y = max((max_y - min_y) / 50, 1)

    best = None
    best_d = None
    y = min_y
    while y <= max_y:
        x = min_x
        while x <= max_x:
            if point_in_polygon(x, y, xs, ys):
                d = (x - cx) ** 2 + (y - cy) ** 2
                if best is None or d < best_d:
                    best, best_d = (x, y), d
            x += step_x
        y += step_y

    return best if best else (cx, cy)


def build_zone_data(path, name_field="Ten_Khu"):
    geo = load_geojson(path)
    zones = []
    for feature in geo["features"]:
        coords = polygon_coords(feature)
        if not coords:
            continue
        pts = [to_svg_xy(p[0], p[1]) for p in coords]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        name = feature["properties"].get(name_field, "Unknown")
        label_x, label_y = find_label_point(xs, ys)
        # Ước lượng độ rộng polygon tại độ cao nhãn để co chữ vừa trong polygon
        bbox_w = max(xs) - min(xs)
        bbox_h = max(ys) - min(ys)
        zones.append({
            "name": name,
            "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
            "cx": label_x,
            "cy": label_y,
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "bboxW": bbox_w,
            "bboxH": bbox_h,
        })
    return zones


# Bảng màu theo loại căn — chỉnh sửa/thêm dòng tại đây nếu có thêm loại mới
CATEGORY_COLORS = {
    "2PN": "#f5a623",
    "2PN ĐẶC BIỆT": "#c0392b",
    "3PN": "#2ecc71",
    "3PN ĐẶC BIỆT": "#2980b9",
    "HÀNH LANG, THANG MÁY": "#95a5a6",
}
DEFAULT_COLOR = "#00bcd4"


def build_building_data(path, category_field="Can"):
    """Lấy TOÀN BỘ thuộc tính (properties) đã điền trong QGIS cho mỗi polygon căn,
    để hiển thị đầy đủ khi rê chuột — không giới hạn ở 2 trường Can/Loai_Can nữa.
    Đồng thời gán màu theo loại căn (CATEGORY_COLORS) để tô polygon."""
    geo = load_geojson(path)
    buildings = []
    for feature in geo["features"]:
        coords = polygon_coords(feature)
        if not coords:
            continue
        pts = [to_svg_xy(p[0], p[1]) for p in coords]
        props = feature.get("properties", {}) or {}
        # Bỏ các giá trị rỗng/None để tooltip gọn gàng, giữ nguyên thứ tự trường trong GeoJSON
        clean_props = {
            str(k): v for k, v in props.items()
            if v is not None and str(v).strip() != "" and str(k).lower() != "id"
        }
        category = str(props.get(category_field, "")).strip()
        color = CATEGORY_COLORS.get(category, DEFAULT_COLOR)
        buildings.append({
            "props": clean_props,
            "category": category,
            "color": color,
            "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
        })
    return buildings


with open(IMAGE_PATH, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

zones_data = build_zone_data(ZONING_GEOJSON)
buildings_data = build_building_data(BUILDING_GEOJSON)


# ==========================================
# TEMPLATE HTML/CSS/JS (SVG + pan-zoom tự viết, không phụ thuộc thư viện ngoài)
# ==========================================
HTML_TEMPLATE = """
<style>
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; }
  #statusText { margin-bottom:8px; color:#555; font-size:14px; font-style: italic; font-family: 'Source Sans Pro', Arial, sans-serif; }
  #backBtn {
    display:none; margin-bottom:8px; padding:7px 16px; border-radius:8px; border:none;
    background:#2563eb; color:white; cursor:pointer; font-size:14px; font-weight:600;
  }
  #backBtn:hover { background:#1d4ed8; }
  #viewport {
    position: relative; width: 100%;
    aspect-ratio: __IMG_W__ / __IMG_H__;   /* luôn khớp tỉ lệ ảnh gốc, không dư/thiếu khoảng trống */
    max-height: 1400px;   /* chỉ chặn trên các màn hình cực lớn, không phụ thuộc vh của iframe */
    margin: 0 auto;
    overflow: hidden;
    background: #000; border-radius: 10px; cursor: grab;
  }
  #viewport.dragging { cursor: grabbing; }
  #stage { position: absolute; top:0; left:0; transform-origin: 0 0; width: 100%; height: 100%; }
  #mapSvg { display:block; width:100%; height:100%; user-select:none; }

  /* Polygon luôn sáng (tô màu + viền) để thấy rõ ranh giới từng khu ngay từ đầu */
  .zone-poly {
    fill: orange; fill-opacity: 0.32; stroke: white; stroke-width: 4; stroke-opacity: 1;
    cursor: pointer; transition: fill-opacity .2s;
  }
  .zone-poly:hover { fill-opacity: 0.5; }
  .zone-poly.zone-dim { fill-opacity: 0.08; stroke-opacity: 0.6; stroke-dasharray: 16 10; cursor: default; }

  /* Nhãn tên khu: giữ hiển thị nhưng thu nhỏ để nằm gọn trong polygon */
  .zone-label {
    fill: white; font-size: 22px; font-weight: 800; font-family: Arial, sans-serif;
    text-anchor: middle; pointer-events: none;
    paint-order: stroke; stroke: rgba(0,0,0,0.65); stroke-width: 3px;
  }

  .building-poly { fill: cyan; fill-opacity: 0.55; stroke: white; stroke-width: 2.5; cursor: pointer; transition: fill-opacity .15s, stroke-width .15s; }
  .building-poly:hover { fill-opacity: 0.8; stroke-width: 3.5; }
  #buildingLayer { display: none; }
  #tooltip {
    position:absolute; display:none; background: rgba(20,20,20,0.92); color:white;
    padding:0; border-radius:8px; font-size:13px; line-height:1.5; pointer-events:none; z-index:10;
    max-width: 260px; white-space:normal; overflow:hidden;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35); font-family: Arial, sans-serif;
  }
  #tooltip .tt-head {
    padding:6px 12px; font-weight:800; font-size:13px; color:#111;
  }
  #tooltip .tt-body { padding:8px 12px; }
  #legend {
    position:absolute; left:10px; bottom:10px; display:none;
    background: rgba(20,20,20,0.75); border-radius:8px; padding:8px 12px;
    font-family: Arial, sans-serif; font-size:12px; color:white; line-height:1.7;
  }
  #legend .legend-item { display:flex; align-items:center; gap:6px; }
  #legend .legend-swatch { width:12px; height:12px; border-radius:3px; flex:0 0 auto; }
  #hint { position:absolute; right:10px; bottom:10px; color:rgba(255,255,255,0.55); font-size:12px; font-family: Arial, sans-serif; pointer-events:none;}
</style>

<div id="statusText">💡 Rê chuột để xem tên phân khu. Click vào bất kỳ đâu trong phân khu Palm River để zoom vào chi tiết.</div>
<button id="backBtn">⬅️ Về tổng quan</button>

<div id="viewport">
  <div id="stage">
    <svg id="mapSvg" viewBox="0 0 __IMG_W__ __IMG_H__" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
      <image href="data:image/jpeg;base64,__IMG_B64__" x="0" y="0" width="__IMG_W__" height="__IMG_H__" />
      <g id="zoneLayer"></g>
      <g id="buildingLayer"></g>
    </svg>
  </div>
  <div id="tooltip"></div>
  <div id="legend"></div>
  <div id="hint">Lăn chuột: zoom · Kéo: di chuyển</div>
</div>

<script>
(function () {
  const IMG_W = __IMG_W__;
  const IMG_H = __IMG_H__;
  const zones = __ZONES_JSON__;
  const buildings = __BUILDINGS_JSON__;

  const viewport = document.getElementById('viewport');
  const stage = document.getElementById('stage');
  const svgEl = document.getElementById('mapSvg');
  const zoneLayer = document.getElementById('zoneLayer');
  const buildingLayer = document.getElementById('buildingLayer');
  const tooltip = document.getElementById('tooltip');
  const legend = document.getElementById('legend');
  const statusText = document.getElementById('statusText');
  const backBtn = document.getElementById('backBtn');

  let scale = 1, tx = 0, ty = 0;
  let currentZoom = null;
  const zonePolyByName = {};   // tra cứu polygon DOM theo tên, tránh escape selector
  const zoneLabelByName = {};

  function applyTransform(animate) {
    stage.style.transition = animate ? 'transform 0.7s cubic-bezier(0.22,1,0.36,1)' : 'none';
    stage.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
  }

  /*
   * Zoom chính xác tới 1 vùng. Vì #viewport luôn giữ đúng tỉ lệ ảnh gốc
   * (CSS aspect-ratio) và #stage/#svg phủ kín 100% viewport ở scale=1,
   * nên 1 đơn vị toạ độ SVG (viewBox) tương ứng đúng bằng
   * viewport.clientWidth/IMG_W (trục x) và viewport.clientHeight/IMG_H (trục y)
   * pixel CSS — tính trực tiếp, không cần reset transform để đo (tránh lệch do
   * timing của transition/reflow).
   */
  function zoomToBBox(bbox, padding) {
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const bsX = vw / IMG_W;
    const bsY = vh / IMG_H;

    const baseW = Math.max(bbox.width * bsX, 1);
    const baseH = Math.max(bbox.height * bsY, 1);
    const baseCx = (bbox.x + bbox.width / 2) * bsX;
    const baseCy = (bbox.y + bbox.height / 2) * bsY;

    const s1 = (vw * (1 - padding)) / baseW;
    const s2 = (vh * (1 - padding)) / baseH;
    scale = Math.min(s1, s2, 3.5);
    tx = vw / 2 - baseCx * scale;
    ty = vh / 2 - baseCy * scale;
    applyTransform(true);
  }

  function resetZoom() {
    scale = 1; tx = 0; ty = 0;
    currentZoom = null;
    applyTransform(true);
    document.querySelectorAll('.zone-poly').forEach(function (el) {
      el.classList.remove('zone-dim');
      el.style.display = '';
    });
    document.querySelectorAll('.zone-label').forEach(function (el) { el.style.display = ''; });
    buildingLayer.style.display = 'none';
    legend.style.display = 'none';
    statusText.textContent = '💡 Rê chuột để xem tên phân khu. Click vào bất kỳ đâu trong phân khu Palm River để zoom vào chi tiết.';
    backBtn.style.display = 'none';
  }

  function zoomToZone(zone) {
    currentZoom = zone.name;

    // Lấy bbox THẬT của polygon đang render (getBBox), đảm bảo khớp 100% với hình vẽ trên màn hình
    const zoneEl = zonePolyByName[zone.name];
    const bb = zoneEl ? zoneEl.getBBox() : { x: zone.bbox[0], y: zone.bbox[1], width: zone.bbox[2]-zone.bbox[0], height: zone.bbox[3]-zone.bbox[1] };
    zoomToBBox(bb, 0.45);

    document.querySelectorAll('.zone-poly').forEach(function (el) {
      if (el.dataset.name === zone.name) {
        el.classList.add('zone-dim');
        el.style.display = '';
      } else {
        el.style.display = 'none';
      }
    });
    document.querySelectorAll('.zone-label').forEach(function (el) { el.style.display = 'none'; });

    if (zone.name.toUpperCase().indexOf('PALM RIVER') !== -1) {
      buildingLayer.style.display = 'block';
      legend.style.display = 'block';
    } else {
      buildingLayer.style.display = 'none';
      legend.style.display = 'none';
    }

    statusText.textContent = '📍 Đang xem chi tiết: ' + zone.name;
    backBtn.style.display = 'inline-block';
  }

  // --- Vẽ các phân khu ---
  zones.forEach(function (zone) {
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', zone.points);
    poly.setAttribute('class', 'zone-poly');
    poly.dataset.name = zone.name;
    poly.addEventListener('click', function () { if (!currentZoom) zoomToZone(zone); });
    poly.addEventListener('mouseenter', function (e) { showTooltip(zone.name, e); });
    poly.addEventListener('mousemove', moveTooltip);
    poly.addEventListener('mouseleave', hideTooltip);
    zoneLayer.appendChild(poly);
    zonePolyByName[zone.name] = poly;

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', zone.cx);
    label.setAttribute('y', zone.cy);
    label.setAttribute('class', 'zone-label');
    label.textContent = zone.name;
    zoneLayer.appendChild(label);
    zoneLabelByName[zone.name] = label;

    // Co chữ vừa bề rộng polygon (ước lượng: ~0.6em/ký tự)
    requestAnimationFrame(function () {
      try {
        const textLen = label.getComputedTextLength();
        const maxW = zone.bboxW * 0.85; // chừa lề 2 bên
        if (textLen > maxW && maxW > 0) {
          const curSize = parseFloat(getComputedStyle(label).fontSize);
          const newSize = Math.max(12, curSize * (maxW / textLen));
          label.style.fontSize = newSize + 'px';
        }
      } catch (e) { /* getComputedTextLength có thể fail nếu ẩn - bỏ qua */ }
    });
  });

  // Dựng nội dung tooltip dạng "thẻ màu" từ TOÀN BỘ thuộc tính đã điền trong QGIS
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  // Chọn màu chữ đen/trắng cho phần đầu thẻ tuỳ độ sáng của màu nền
  function readableTextColor(hex) {
    const c = hex.replace('#', '');
    const r = parseInt(c.substring(0, 2), 16), g = parseInt(c.substring(2, 4), 16), b = parseInt(c.substring(4, 6), 16);
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.6 ? '#111' : '#fff';
  }
  function showBuildingTooltip(b, e) {
    const props = b.props || {};
    const keys = Object.keys(props).filter(function (k) { return k !== 'Can'; });
    const bodyHtml = keys.length
      ? keys.map(function (k) { return '<b>' + escapeHtml(k) + ':</b> ' + escapeHtml(props[k]); }).join('<br>')
      : '';
    const headText = b.category || 'Thông tin căn';
    tooltip.innerHTML =
      '<div class="tt-head" style="background:' + b.color + ';color:' + readableTextColor(b.color) + ';">' + escapeHtml(headText) + '</div>' +
      (bodyHtml ? '<div class="tt-body">' + bodyHtml + '</div>' : '');
    tooltip.style.borderLeft = '4px solid ' + b.color;
    tooltip.style.display = 'block';
    moveTooltip(e);
  }

  // --- Vẽ các căn hộ (ẩn sẵn, chỉ hiện khi zoom vào Palm River), tô màu theo loại căn ---
  const seenCategories = {}; // dùng để dựng legend không trùng lặp, giữ thứ tự xuất hiện
  buildings.forEach(function (b) {
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', b.points);
    poly.setAttribute('class', 'building-poly');
    poly.style.fill = b.color;
    poly.addEventListener('mouseenter', function (e) { showBuildingTooltip(b, e); });
    poly.addEventListener('mousemove', moveTooltip);
    poly.addEventListener('mouseleave', hideTooltip);
    buildingLayer.appendChild(poly);

    if (b.category && !seenCategories[b.category]) {
      seenCategories[b.category] = b.color;
    }
  });

  // Dựng chú thích màu (legend) từ các loại căn thực có trong dữ liệu
  const legendHtml = Object.keys(seenCategories).map(function (cat) {
    return '<div class="legend-item"><span class="legend-swatch" style="background:' + seenCategories[cat] + '"></span>' + escapeHtml(cat) + '</div>';
  }).join('');
  legend.innerHTML = legendHtml;

  function showTooltip(html, e) {
    tooltip.style.borderLeft = 'none';
    tooltip.innerHTML = '<div class="tt-body">' + html + '</div>';
    tooltip.style.display = 'block';
    moveTooltip(e);
  }
  function moveTooltip(e) {
    const rect = viewport.getBoundingClientRect();
    tooltip.style.left = (e.clientX - rect.left + 16) + 'px';
    tooltip.style.top = (e.clientY - rect.top + 16) + 'px';
  }
  function hideTooltip() { tooltip.style.display = 'none'; }

  backBtn.addEventListener('click', resetZoom);

  // --- Bonus: lăn chuột để zoom, kéo để pan (tự viết, không cần thư viện ngoài) ---
  viewport.addEventListener('wheel', function (e) {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const delta = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const newScale = Math.min(Math.max(scale * delta, 1), 10);
    tx = mx - (mx - tx) * (newScale / scale);
    ty = my - (my - ty) * (newScale / scale);
    scale = newScale;
    applyTransform(false);
  }, { passive: false });

  let dragging = false, lastX = 0, lastY = 0;
  viewport.addEventListener('mousedown', function (e) {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    viewport.classList.add('dragging');
  });
  window.addEventListener('mouseup', function () { dragging = false; viewport.classList.remove('dragging'); });
  window.addEventListener('mousemove', function (e) {
    if (!dragging) return;
    tx += (e.clientX - lastX);
    ty += (e.clientY - lastY);
    lastX = e.clientX; lastY = e.clientY;
    applyTransform(false);
  });

  resetZoom();

  // Báo chiều cao thực tế cho Streamlit qua postMessage (đúng cơ chế Streamlit hỗ trợ),
  // thay vì tự set frameElement.style.height (dễ đo sai lúc layout chưa ổn định).
  function reportFrameHeight() {
    const h = document.documentElement.scrollHeight;
    window.parent.postMessage({ isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: h }, '*');
  }
  window.addEventListener('resize', reportFrameHeight);
  if (window.ResizeObserver) {
    new ResizeObserver(reportFrameHeight).observe(document.documentElement);
  }
  setTimeout(reportFrameHeight, 50);
  setTimeout(reportFrameHeight, 300);
  setTimeout(reportFrameHeight, 1000);
})();
</script>
"""

html = (
    HTML_TEMPLATE
    .replace("__IMG_W__", str(IMG_WIDTH))
    .replace("__IMG_H__", str(IMG_HEIGHT))
    .replace("__IMG_B64__", img_b64)
    .replace("__ZONES_JSON__", json.dumps(zones_data, ensure_ascii=False))
    .replace("__BUILDINGS_JSON__", json.dumps(buildings_data, ensure_ascii=False))
)

# height ở đây chỉ là giá trị khởi tạo ban đầu; #viewport bên trong tự co giãn theo
# aspect-ratio nên không còn dư khoảng trắng / phải cuộn để xem hết ảnh.
components.html(html, height=950, scrolling=False)