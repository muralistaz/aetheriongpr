"""
============================================================
DIY GPR — Vizuallaşdırma 1: Canlı Radargram/SAR Şəkil Render
============================================================

Bu modul, Modul 4-ün (DSP) davamlı istehsal etdiyi range-profile
axınını (B-scan waterfall kimi) VƏ Modul 6-nın (SAR) fokuslanmış
görüntüsünü CANLI (davamlı yenilənən) PNG şəkillər kimi saxlayır.

DÜZƏLİŞ TARİXÇƏSİ: Əvvəlki versiya, artıq layihədən çıxarılmış
"Modul 5" (RadargramBuilder + 1D threshold detection) sinifindən
asılı idi. Bu, silinib — LiveRadargramRenderer indi Modul 4-ün
sadə range-profile massivindən BİRBAŞA işləyir, detection overlay-i
isə YALNIZ SAR (Modul 6) formatında (x_m/y_m, "range_m" YOX) qəbul edir.

HEADLESS DİZAYN: Jetson Orin Nano uçuş zamanı fiziki monitor olmaya
bilər, ona görə bu modul HEÇ VAXT ekran açmağa çalışmır — sadəcə
şəkilləri fayla yazır. Bu fayllar:
  1. Yerli SD/SSD-də saxlanılır (uçuşdan sonra baxmaq üçün)
  2. Alfa 5.8GHz linki üzərindən yer stansiyasına göndərilə bilər
     (fayl paylaşma/sync mexanizmi ilə, bu modulun məsuliyyəti xaricindədir)
============================================================
"""

import time
import numpy as np

import matplotlib
matplotlib.use("Agg")  # Ekran olmadan (headless) işləmək üçün
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon


# ============================================================
# 1. CANLI RANGE-PROFILE WATERFALL RENDER (sadə, detection-sız)
# ============================================================
class LiveRadargramRenderer:
    """
    Modul 4-ün (DSP pipeline) hər scan-da istehsal etdiyi
    `range_profile_clean` massivini, ÖZ DAXİLİNDƏ topladığı sadə
    bir matrisdə saxlayır və davamlı olaraq PNG-yə render edir.

    QEYD: Bu sinif artıq XARİCİ "RadargramBuilder" obyektindən ASILI
    DEYİL (əvvəlki versiyadan fərqli olaraq) — özü daxili buferini
    idarə edir. Bu, sadə "xam siqnal monitorinqi" vasitəsidir,
    RƏSMİ HƏDƏF AŞKARLAMA SAR (Modul 6) tərəfindən edilir — bu render
    yalnız operatora "sistem işləyir, siqnal belə görünür" göstərmək
    üçündür, detection qərarı vermir.
    """

    def __init__(self, range_axis, max_scans=500,
                 output_path="/mnt/user-data/outputs/radargram_live.png",
                 render_every_n_scans=5, colormap="viridis"):
        self.range_axis = range_axis
        self.max_scans = max_scans
        self.output_path = output_path
        self.render_every_n_scans = render_every_n_scans
        self.colormap = colormap
        self._scan_counter = 0
        self._matrix = np.zeros((0, len(range_axis)))

    def add_scan(self, range_profile_clean):
        """Yeni scan-ı daxili buferə əlavə edir (rolling buffer)."""
        row = np.asarray(range_profile_clean).reshape(1, -1)
        self._matrix = np.vstack([self._matrix, row])
        if self._matrix.shape[0] > self.max_scans:
            self._matrix = self._matrix[1:, :]

    def update(self, range_profile_clean):
        """
        Hər yeni scan gələndə çağırılır: buferə əlavə edir, sonra
        yalnız `render_every_n_scans` aralığında faktiki render edir.
        """
        self.add_scan(range_profile_clean)
        self._scan_counter += 1
        if self._scan_counter % self.render_every_n_scans != 0:
            return
        self._render()

    def _render(self):
        if self._matrix.shape[0] == 0:
            return

        fig, ax = plt.subplots(figsize=(12, 6))

        extent = [0, self._matrix.shape[0], self.range_axis[-1], self.range_axis[0]]

        im = ax.imshow(
            self._matrix.T, aspect="auto", cmap=self.colormap,
            extent=extent, interpolation="bilinear",
        )

        ax.set_xlabel("Scan nömrəsi (uçuş istiqaməti)")
        ax.set_ylabel("Dərinlik (m)")
        ax.set_title(
            f"Canlı Range-Profile Monitorinqi — {self._matrix.shape[0]} scan "
            f"(son yenilənmə: {time.strftime('%H:%M:%S')})\n"
            f"[Xam siqnal göstəricisi — rəsmi hədəf aşkarlama SAR (Modul 6) tərəfindən edilir]"
        )
        plt.colorbar(im, ax=ax, label="Əks-səda gücü")

        plt.tight_layout()
        plt.savefig(self.output_path, dpi=100)
        plt.close(fig)


# ============================================================
# 2. CANLI SAR FOKUSLANMIŞ GÖRÜNTÜ RENDER
# ============================================================
class LiveSARRenderer:
    """
    Modul 6-dakı SAR görüntüsünü (compute_image() nəticəsini) PNG
    şəklinə çevirir, aşkarlanan hədəfləri üzərinə işarələyir.
    """

    def __init__(self, output_path="/mnt/user-data/outputs/sar_image_live.png",
                 colormap="inferno"):
        self.output_path = output_path
        self.colormap = colormap

    def render(self, sar_result, detections=None, true_target_position=None,
               boundary_polygon_vertices_m=None):
        """
        sar_result: SARImageFormation.compute_image()-dən qayıdan dict
        detections: SARTargetDetector.detect()-dən qayıdan siyahı —
            hər elementdə OPSIONAL 'marked' sahəsi ola bilər
            (target_map_generator.py ilə UYĞUN status göstərmək üçün)
        true_target_position: (x, y) tuple — YALNIZ test/validasiya
            məqsədilə, real sahə istifadəsində None olmalıdır
        boundary_polygon_vertices_m: UWB marker sərhədi (varsa, üzərinə
            çəkilir — operator canlı görüntüdə sərhəddən kənara
            çıxıb-çıxmadığını dərhal görə bilsin deyə)
        """
        image_db = sar_result["image_db"]
        x_axis = sar_result["x_axis"]
        y_axis = sar_result["y_axis"]

        fig, ax = plt.subplots(figsize=(10, 8))

        extent = [x_axis[0], x_axis[-1], y_axis[0], y_axis[-1]]
        im = ax.imshow(
            image_db, aspect="equal", cmap=self.colormap,
            extent=extent, origin="lower", interpolation="bilinear",
        )

        ax.set_xlabel("X (m, uçuş istiqaməti)")
        ax.set_ylabel("Y (m, uçuşa perpendikulyar)")
        ax.set_title(f"SAR Fokuslanmış Görüntü — Dərinlik: {sar_result['depth_m']:.2f}m")
        plt.colorbar(im, ax=ax, label="Əks-səda gücü (dB)")

        if boundary_polygon_vertices_m:
            poly_patch = MplPolygon(
                boundary_polygon_vertices_m, closed=True,
                fill=False, edgecolor="cyan", linewidth=2, linestyle="--",
                label="UWB sərhəd",
            )
            ax.add_patch(poly_patch)

        if detections:
            for det in detections:
                is_marked = det.get("marked") is True
                if is_marked:
                    # İşarələnmiş hədəf: yaşıl dairə (təsdiqlənmiş status)
                    ax.plot(det["x_m"], det["y_m"], "o", color="lime",
                            markersize=16, markeredgewidth=2, markeredgecolor="black")
                else:
                    # Hələ işarələnməmiş: ağ "+" (əvvəlki davranış)
                    ax.plot(det["x_m"], det["y_m"], "w+", markersize=15, markeredgewidth=2)

                status_label = "✓" if is_marked else f"{det['confidence']:.2f}"
                ax.annotate(
                    status_label,
                    (det["x_m"], det["y_m"]),
                    textcoords="offset points", xytext=(8, 8),
                    color="white", fontsize=9, fontweight="bold",
                )

        if true_target_position:
            ax.plot(*true_target_position, "g*", markersize=18,
                    label="Real mövqe (test)")

        if boundary_polygon_vertices_m or true_target_position:
            ax.legend(loc="upper right", fontsize=8)

        plt.tight_layout()
        plt.savefig(self.output_path, dpi=120)
        plt.close(fig)
        print(f"[OK] SAR görüntüsü saxlanıldı: {self.output_path}")


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    import numpy as np

    print("=== LiveRadargramRenderer testi (sintetik range-profile axını) ===")
    range_axis = np.linspace(0, 2.0, 100)
    renderer = LiveRadargramRenderer(
        range_axis=range_axis,
        output_path="/mnt/user-data/outputs/radargram_live_test.png",
        render_every_n_scans=3,
    )

    np.random.seed(1)
    for i in range(10):
        fake_profile = 0.05 * np.random.randn(len(range_axis))
        if 5 <= i <= 8:
            fake_profile[30] += 0.3  # süni hədəf
        renderer.update(fake_profile)
    print(f"[OK] Test tamamlandı, {renderer._matrix.shape[0]} scan buferə yazıldı.\n")

    print("=== LiveSARRenderer testi (marked statusu + sərhəd poliqonu ilə) ===")
    x_axis = np.linspace(0, 6, 60)
    y_axis = np.linspace(-2, 2, 40)
    fake_image_db = -30 + 5 * np.random.randn(len(y_axis), len(x_axis))
    fake_image_db[20, 30] = 5.0  # süni parlaq hədəf

    fake_sar_result = {
        "image_db": fake_image_db, "x_axis": x_axis, "y_axis": y_axis, "depth_m": 0.3,
    }
    fake_detections = [
        {"x_m": 3.0, "y_m": 0.0, "confidence": 0.8, "marked": True},
        {"x_m": 4.5, "y_m": -1.0, "confidence": 0.4, "marked": False},
    ]

    sar_renderer = LiveSARRenderer(output_path="/mnt/user-data/outputs/sar_image_live_test.png")
    sar_renderer.render(
        fake_sar_result, detections=fake_detections,
        boundary_polygon_vertices_m=[(0, -2), (0, 2), (6, 2), (6, -2)],
    )
