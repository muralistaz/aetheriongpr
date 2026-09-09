"""
============================================================
DIY GPR — Vizuallaşdırma 3: Log/Export Formatı (KML/GeoJSON)
============================================================

Bu modul, aşkarlanmış hədəfləri (GPS koordinatları ilə) GIS
proqramlarında (QGIS, Google Earth, ArcGIS) birbaşa açıla bilən
standart formatlara ixrac edir:

  - KML: Google Earth-ün öz formatı, XML-əsaslı
  - GeoJSON: müasir, geniş dəstəklənən (QGIS, web-xəritələr, və s.)

Hər iki format, hər hədəf üçün: GPS koordinatı, dərinlik, güvən
səviyyəsi, timestamp və peak gücü metadata kimi saxlayır.
============================================================
"""

import json
import time
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


# ============================================================
# 1. KML EXPORT
# ============================================================
def export_to_kml(gps_detections, output_path="detections.kml",
                   document_name="GPR Mina Aşkarlama Nəticələri"):
    """
    Hədəfləri KML formatına ixrac edir (Google Earth-də açıla bilər).

    gps_detections: TargetMapGenerator.convert_detections_to_gps()-dən
        gələn siyahı (hər elementdə 'lat', 'lon', 'depth_m',
        'confidence', 'peak_db' sahələri olmalıdır)
    """
    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = SubElement(kml, "Document")

    name_elem = SubElement(document, "name")
    name_elem.text = document_name

    # --- Güvən səviyyəsinə görə rəng, İŞARƏLƏNMƏ statusuna görə forma ---
    # KML rəng formatı: aabbggrr (alfa, mavi, yaşıl, qırmızı — tərs sıra!)
    style_high_unmarked = SubElement(document, "Style", id="highConfidenceUnmarked")
    icon_style_high_u = SubElement(SubElement(style_high_unmarked, "IconStyle"), "color")
    icon_style_high_u.text = "ff0000ff"  # qırmızı (yüksək güvən, işarələnməyib)

    style_low_unmarked = SubElement(document, "Style", id="lowConfidenceUnmarked")
    icon_style_low_u = SubElement(SubElement(style_low_unmarked, "IconStyle"), "color")
    icon_style_low_u.text = "ff00ffff"  # sarı (aşağı güvən, işarələnməyib)

    style_marked = SubElement(document, "Style", id="physicallyMarked")
    icon_style_marked = SubElement(SubElement(style_marked, "IconStyle"), "color")
    icon_style_marked.text = "ff00ff00"  # yaşıl (fiziki işarələnib — təsdiqlənmiş)

    for i, det in enumerate(gps_detections):
        placemark = SubElement(document, "Placemark")

        is_marked = det.get("marked") is True
        mark_label = "✓ FİZİKİ İŞARƏLƏNİB" if is_marked else "⚠ hələ işarələnməyib"

        name = SubElement(placemark, "name")
        name.text = f"Hədəf #{i+1} ({'İşarələnib' if is_marked else 'Aşkarlanıb'})"

        description = SubElement(placemark, "description")
        description.text = (
            f"Status: {mark_label}\n"
            f"Dərinlik: {det['depth_m']:.2f} m\n"
            f"Güvən: {det['confidence']:.2f}\n"
            f"Peak güc: {det.get('peak_db', 'N/A')} dB\n"
            f"Aşkarlama vaxtı: {det.get('timestamp', 'N/A')}\n"
            f"İşarələmə vaxtı: {det.get('mark_timestamp', 'N/A')}"
        )

        style_url = SubElement(placemark, "styleUrl")
        if is_marked:
            style_url.text = "#physicallyMarked"
        else:
            style_url.text = "#highConfidenceUnmarked" if det["confidence"] > 0.5 else "#lowConfidenceUnmarked"

        point = SubElement(placemark, "Point")
        coordinates = SubElement(point, "coordinates")
        # KML formatı: lon,lat,alt (DİQQƏT: lat/lon sırası TƏRSDİR!)
        coordinates.text = f"{det['lon']},{det['lat']},0"

    # Gözəl formatlaşdırılmış XML çıxışı üçün
    rough_string = tostring(kml, "utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    print(f"[OK] KML faylı yaradıldı: {output_path} ({len(gps_detections)} hədəf)")


# ============================================================
# 2. GEOJSON EXPORT
# ============================================================
def export_to_geojson(gps_detections, output_path="detections.geojson"):
    """
    Hədəfləri GeoJSON formatına ixrac edir (QGIS, web-xəritələr üçün).

    GeoJSON standartına görə, koordinatlar [longitude, latitude] sırası
    ilə yazılmalıdır (KML ilə eyni sıra, lat/lon-un tərsinə).
    """
    features = []

    for i, det in enumerate(gps_detections):
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [det["lon"], det["lat"]],
            },
            "properties": {
                "id": i + 1,
                "depth_m": round(det["depth_m"], 3),
                "confidence": round(det["confidence"], 3),
                "peak_db": det.get("peak_db"),
                "timestamp": det.get("timestamp"),
                "marked_status": det.get("marked") is True,
                "mark_timestamp": det.get("mark_timestamp"),
                "detection_type": "GPR_SAR",
            },
        }
        features.append(feature)

    geojson_data = {
        "type": "FeatureCollection",
        "metadata": {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "DIY SFCW GPR — Mina Aşkarlama Sistemi",
            "total_detections": len(gps_detections),
        },
        "features": features,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, indent=2, ensure_ascii=False)

    print(f"[OK] GeoJSON faylı yaradıldı: {output_path} ({len(gps_detections)} hədəf)")


# ============================================================
# 3. HƏR İKİSİNİ BİRLİKDƏ İXRAC ETMƏK ÜÇÜN KÖMƏK FUNKSİYASI
# ============================================================
def export_all_formats(gps_detections, output_dir="/mnt/user-data/outputs", base_filename="gpr_detections"):
    """Bir çağırışla həm KML, həm GeoJSON faylını yaradır."""
    kml_path = f"{output_dir}/{base_filename}.kml"
    geojson_path = f"{output_dir}/{base_filename}.geojson"

    export_to_kml(gps_detections, output_path=kml_path)
    export_to_geojson(gps_detections, output_path=geojson_path)

    return kml_path, geojson_path


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    # Sintetik test — bəziləri işarələnib, bəziləri hələ yox
    fake_gps_detections = [
        {
            "lat": 40.123500, "lon": 47.654400,
            "depth_m": 0.30, "confidence": 0.47,
            "peak_db": -14.4, "timestamp": 12.5,
            "marked": True, "mark_timestamp": 45.2,
        },
        {
            "lat": 40.123600, "lon": 47.654500,
            "depth_m": 0.45, "confidence": 0.72,
            "peak_db": -10.1, "timestamp": 18.2,
            "marked": False, "mark_timestamp": None,
        },
        {
            "lat": 40.123450, "lon": 47.654350,
            "depth_m": 0.20, "confidence": 0.31,
            "peak_db": -18.9, "timestamp": 25.0,
            "marked": False, "mark_timestamp": None,
        },
    ]

    kml_path, geojson_path = export_all_formats(
        fake_gps_detections,
        output_dir="/mnt/user-data/outputs",
        base_filename="test_detections",
    )

    print(f"\n[OK] Test tamamlandı:")
    print(f"     KML: {kml_path}")
    print(f"     GeoJSON: {geojson_path}")
