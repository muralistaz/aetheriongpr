"""
============================================================
DIY GPR — Vizuallaşdırma 2: Top-Down "Hədəf Xəritəsi" (GPS koordinatlı)
============================================================

Bu modul, Modul 6-dan (SAR detection) gələn yerli (ENU, metr) koordinatlı
hədəfləri, RTK GPS referans nöqtəsi ilə birləşdirərək REAL GPS
koordinatlarına (lat/lon) çevirir və ANAMA-ya təqdim edilə biləcək
peşəkar bir "top-down" xəritə şəkli yaradır.
============================================================
"""

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon


# ============================================================
# 1. TƏRS ÇEVİRMƏ: ENU (yerli, metr) -> GPS (lat/lon)
# ============================================================
def enu_to_gps(east_m, north_m, ref_lat, ref_lon):
    """
    Modul 6-dakı gps_to_enu()-nun TƏRSİ. Yerli Cartesian (E, N)
    koordinatlarını, referans nöqtəyə görə real lat/lon-a çevirir.

    QEYD: Sadələşdirilmiş düz-xətli approksimasiya (kiçik sahələr üçün
    kifayət qədər dəqiqdir, adətən yüz metrlərlə ölçüdə <1sm xəta).
    Böyük sahələr üçün pyproj kimi tam geodeziya kitabxanası tövsiyə olunur.
    """
    EARTH_RADIUS = 6378137.0  # metr, WGS84

    d_lat = north_m / EARTH_RADIUS
    d_lon = east_m / (EARTH_RADIUS * np.cos(np.radians(ref_lat)))

    lat = ref_lat + np.degrees(d_lat)
    lon = ref_lon + np.degrees(d_lon)

    return lat, lon


# ============================================================
# 2. HƏDƏF XƏRİTƏSİ GENERATORU
# ============================================================
class TargetMapGenerator:
    """
    SAR detection nəticələrini GPS koordinatlı, ANAMA-təqdim-hazır
    top-down xəritəyə çevirir.
    """

    def __init__(self, ref_lat, ref_lon, ref_alt=0.0):
        """
        ref_lat, ref_lon, ref_alt: Uçuşun başlanğıc RTK GPS referans
            nöqtəsi — bütün ENU koordinatları buna görə hesablanıb
            (Modul 6-dakı gps_to_enu() ilə eyni referans olmalıdır!)
        """
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon
        self.ref_alt = ref_alt

    def convert_detections_to_gps(self, detections):
        """
        Modul 6-nın detections siyahısını (x_m, y_m yerli koordinatlarla)
        götürüb, hər birinə 'lat' və 'lon' sahələri əlavə edir.
        """
        gps_detections = []
        for det in detections:
            lat, lon = enu_to_gps(det["x_m"], det["y_m"], self.ref_lat, self.ref_lon)
            det_with_gps = dict(det)  # orijinalı dəyişməmək üçün kopyala
            det_with_gps["lat"] = lat
            det_with_gps["lon"] = lon
            gps_detections.append(det_with_gps)
        return gps_detections

    def generate_map(
        self,
        detections,
        survey_area_bounds_m=None,
        boundary_polygon_vertices_m=None,
        output_path="/mnt/user-data/outputs/target_map.png",
        title="Mina Aşkarlama Sahəsi — Hədəf Xəritəsi",
    ):
        """
        Top-down xəritəni yaradır, PNG kimi saxlayır.

        survey_area_bounds_m: (x_min, x_max, y_min, y_max) tuple —
            DÜZBUCAQLI sahə üçün (əvvəlki sadə sahələr, GPS-marker
            olmadan aparılan testlər üçün hələ dəstəklənir).

        boundary_polygon_vertices_m: list of (x, y) tuple — UWB
            marker-lərdən qurulan İXTİYARİ POLİQON sərhəd (üçbucaq
            daxil olmaqla). VERİLƏRSƏ, survey_area_bounds_m-dən
            ÜSTÜN tutulur, çünki real sahə formasını dəqiq göstərir.
            (uwb_boundary_path_planning.py-dəki boundary_polygon.
            exterior.coords-dan birbaşa əldə edilə bilər.)

        QEYD: Əgər sizin sahəniz UWB marker-lərlə (3 və ya daha çox)
        müəyyənləşdirilibsə, HƏMİŞƏ boundary_polygon_vertices_m istifadə
        edin — düzbucaqlı fərziyyəsi, üçbucaq/ixtiyari sahədə YANLIŞ
        vizual təəssürat yaradar (məsələn, üçbucağın kənarından kənarda
        qalan "boş" sahəni belə skan edilmiş kimi göstərər).
        """
        gps_detections = self.convert_detections_to_gps(detections)

        fig, ax = plt.subplots(figsize=(10, 10))

        # --- Sahə sərhədini göstər: POLİQON prioritetlidir ---
        if boundary_polygon_vertices_m:
            poly_patch = MplPolygon(
                boundary_polygon_vertices_m, closed=True,
                fill=True, facecolor="lightgray", edgecolor="black",
                linewidth=1.5, alpha=0.3, label="Skan edilmiş sahə (UWB sərhəd)",
            )
            ax.add_patch(poly_patch)

            # Marker mövqelərini özlərini də göstərək (künc nöqtələri)
            marker_xs = [v[0] for v in boundary_polygon_vertices_m]
            marker_ys = [v[1] for v in boundary_polygon_vertices_m]
            ax.scatter(
                marker_xs, marker_ys, c="blue", s=100, marker="^",
                edgecolors="black", linewidths=1, zorder=4,
                label="UWB sərhəd markeri",
            )
        elif survey_area_bounds_m:
            x_min, x_max, y_min, y_max = survey_area_bounds_m
            rect = plt.Rectangle(
                (x_min, y_min), x_max - x_min, y_max - y_min,
                fill=True, facecolor="lightgray", edgecolor="black",
                linewidth=1.5, alpha=0.3, label="Skan edilmiş sahə",
            )
            ax.add_patch(rect)

        # --- Hədəfləri göstər: rəng=güvən, FORMA=işarələnmə statusu ---
        if gps_detections:
            marked_dets = [d for d in gps_detections if d.get("marked") is True]
            unmarked_dets = [d for d in gps_detections if d.get("marked") is not True]

            if unmarked_dets:
                xs = [d["x_m"] for d in unmarked_dets]
                ys = [d["y_m"] for d in unmarked_dets]
                confidences = [d["confidence"] for d in unmarked_dets]
                scatter_unmarked = ax.scatter(
                    xs, ys, c=confidences, s=200, cmap="YlOrRd",
                    edgecolors="black", linewidths=1.5, vmin=0, vmax=1,
                    zorder=5, marker="X",
                    label="Aşkarlanıb, HƏLƏ İŞARƏLƏNMƏYİB",
                )
                plt.colorbar(scatter_unmarked, ax=ax, label="Aşkarlama güvəni")

            if marked_dets:
                xs = [d["x_m"] for d in marked_dets]
                ys = [d["y_m"] for d in marked_dets]
                confidences = [d["confidence"] for d in marked_dets]
                # İşarələnmiş hədəflər: dolu dairə + yaşıl haşiyə —
                # "fiziki olaraq təsdiqlənib, boya ilə işarələnib" statusu
                ax.scatter(
                    xs, ys, c=confidences, s=280, cmap="YlOrRd",
                    edgecolors="green", linewidths=3, vmin=0, vmax=1,
                    zorder=6, marker="o",
                    label="TƏSDİQLƏNİB VƏ FİZİKİ İŞARƏLƏNİB",
                )

            # Hər hədəfin yanına GPS koordinatı, dərinlik VƏ status yaz
            for det in gps_detections:
                mark_status = "✓ İŞARƏLƏNİB" if det.get("marked") is True else "⚠ işarələnməyib"
                label = (
                    f"  {det['lat']:.6f}°, {det['lon']:.6f}°\n"
                    f"  Dərinlik: {det['depth_m']:.2f}m | {mark_status}"
                )
                ax.annotate(
                    label, (det["x_m"], det["y_m"]),
                    fontsize=7, textcoords="offset points", xytext=(10, 5),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
                )

        ax.set_xlabel("Şərq (m, referans nöqtəyə görə)")
        ax.set_ylabel("Şimal (m, referans nöqtəyə görə)")
        ax.set_title(
            f"{title}\n"
            f"Referans: {self.ref_lat:.6f}°, {self.ref_lon:.6f}° | "
            f"{len(gps_detections)} hədəf aşkarlandı"
        )
        ax.set_aspect("equal")
        ax.grid(True, linestyle="--", alpha=0.4)
        if survey_area_bounds_m or boundary_polygon_vertices_m or gps_detections:
            ax.legend(loc="upper right", fontsize=8)

        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close(fig)

        marked_count = sum(1 for d in gps_detections if d.get("marked") is True)
        print(f"[OK] Hədəf xəritəsi saxlanıldı: {output_path}")
        print(f"     {len(gps_detections)} hədəf ({marked_count} işarələnib, "
              f"{len(gps_detections) - marked_count} hələ işarələnməyib):")
        for i, det in enumerate(gps_detections):
            status = "İŞARƏLƏNİB" if det.get("marked") is True else "işarələnməyib"
            print(
                f"       #{i+1}: {det['lat']:.6f}°, {det['lon']:.6f}° "
                f"(dərinlik={det['depth_m']:.2f}m, güvən={det['confidence']:.2f}, {status})"
            )

        return gps_detections


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    # Sintetik test: bəziləri işarələnib, bəziləri hələ yox
    fake_detections = [
        {"x_m": 1.0, "y_m": -0.05, "depth_m": 0.30, "peak_db": -14.4,
         "confidence": 0.47, "marked": True},
        {"x_m": 3.2, "y_m": 0.8, "depth_m": 0.45, "peak_db": -10.1,
         "confidence": 0.72, "marked": False},
        {"x_m": 5.5, "y_m": -1.2, "depth_m": 0.20, "peak_db": -18.9,
         "confidence": 0.31, "marked": False},
    ]

    REF_LAT = 40.123456
    REF_LON = 47.654321

    map_generator = TargetMapGenerator(ref_lat=REF_LAT, ref_lon=REF_LON)

    # --- Test A: köhnə üsul, düzbucaqlı sahə (hələ dəstəklənir) ---
    map_generator.generate_map(
        fake_detections,
        survey_area_bounds_m=(0, 6, -2, 2),
        title="Test A — Düzbucaqlı Sahə (marked statusu ilə)",
        output_path="/mnt/user-data/outputs/target_map_rectangle.png",
    )

    # --- Test B: YENİ üsul, UWB marker-lərdən gələn ÜÇBUCAQ sərhəd ---
    triangle_boundary = [(0.0, 0.0), (0.0, 20.0), (21.28, 0.0)]
    map_generator.generate_map(
        fake_detections,
        boundary_polygon_vertices_m=triangle_boundary,
        title="Test B — UWB Üçbucaq Sərhəd (real sahə forması)",
        output_path="/mnt/user-data/outputs/target_map_triangle.png",
    )
