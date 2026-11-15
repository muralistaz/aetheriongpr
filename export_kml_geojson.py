"""
============================================================
DIY GPR — Vizuallaşdırma 3: Log/Export Formatı (KML/GeoJSON)
============================================================
"""

import json
import time
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


def export_to_kml(gps_detections, output_path="detections.kml",
                   document_name="GPR Mina Aşkarlama Nəticələri"):
    """KML formatına ixrac edir (Google Earth-də açıla bilər)."""
    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = SubElement(kml, "Document")
    name_elem = SubElement(document, "name")
    name_elem.text = document_name

    style_high_unmarked = SubElement(document, "Style", id="highConfidenceUnmarked")
    icon_style_high_u = SubElement(SubElement(style_high_unmarked, "IconStyle"), "color")
    icon_style_high_u.text = "ff0000ff" 

    style_low_unmarked = SubElement(document, "Style", id="lowConfidenceUnmarked")
    icon_style_low_u = SubElement(SubElement(style_low_unmarked, "IconStyle"), "color")
    icon_style_low_u.text = "ff00ffff" 

    style_marked = SubElement(document, "Style", id="physicallyMarked")
    icon_style_marked = SubElement(SubElement(style_marked, "IconStyle"), "color")
    icon_style_marked.text = "ff00ff00" 

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
        coordinates.text = f"{det['lon']},{det['lat']},0"

    rough_string = tostring(kml, "utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    print(f"[OK] KML faylı yaradıldı: {output_path} ({len(gps_detections)} hədəf)")

def export_to_geojson(gps_detections, output_path="detections.geojson"):
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

def export_all_formats(gps_detections, output_dir="/mnt/user-data/outputs", base_filename="gpr_detections"):
    """
    Bir çağırışla həm KML, həm GeoJSON faylını yaradır. KML prioritetlidir.
    DİQQƏT (FALLBACK): Əgər hədəf siyahısı boşdursa, operatoru xəbərdar edir və boş fayl yaratmır.
    """
    if not gps_detections:
        print("[DİQQƏT - FALLBACK] Heç bir hədəf tapılmadı! Fayllar yaradılmadı. Bu, sistem xətası ola bilər və ya sahə həqiqətən təmizdir.")
        return None, None

    kml_path = f"{output_dir}/{base_filename}.kml"
    geojson_path = f"{output_dir}/{base_filename}.geojson"

    export_to_kml(gps_detections, output_path=kml_path)
    export_to_geojson(gps_detections, output_path=geojson_path)

    return kml_path, geojson_path
