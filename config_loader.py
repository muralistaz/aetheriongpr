"""
============================================================
DIY GPR — Sistem İnfrastrukturu 1: Konfiqurasiya Yükləyicisi
============================================================

Bu modul, system_config.json faylını oxuyur, DOĞRULAYIR (validasiya)
və bütün digər modullara (RF nəzarət, DSP, SAR, return-to-mark, UWB
marşrut planlaşdırması) TİPLƏNMİŞ, strukturlaşdırılmış giriş verir.

NİYƏ AYRI YÜKLƏYİCİ SİNİF, HƏR MODULUN ÖZÜ JSON OXUMASIN:
  1. Fayl yolu, kodlaşdırma, xəta idarəetməsi BİR YERDƏ həll olunur
  2. Validasiya (tələb olunan sahələrin mövcudluğu) MƏRKƏZİ yoxlanılır
     — səhv/əskik konfiqurasiya, sistemin YARISI işə düşdükdən sonra
     yox, DƏRHAL (başlanğıcda) aşkarlanır
  3. Modullar `config.rf_frontend.tx_power_dbm` kimi OXUNAQLI sintaksislə
     yazılır, `config["rf_frontend"]["tx_power"]["value_dbm"]` kimi
     "dırnaqlı" JSON-gəzmə əvəzinə
============================================================
"""

import json
from types import SimpleNamespace


class ConfigValidationError(Exception):
    """Konfiqurasiya faylında tələb olunan sahə əskik və ya səhv olduqda."""
    pass


class SystemConfig:
    """
    system_config.json-u yükləyir, doğrulayır, tipləndirilmiş giriş verir.
    """

    # Bu sahələr HƏMİŞə mövcud olmalıdır — yoxdursa, sistem başlamamalıdır
    REQUIRED_TOP_LEVEL_KEYS = [
        "rf_frontend", "antenna", "dsp_processing",
        "flight_platform", "return_to_mark", "uwb_boundary",
    ]

    def __init__(self, config_path="system_config.json"):
        self.config_path = config_path
        self._raw_dict = None
        self.load()

    def load(self):
        """Faylı oxuyur, JSON-u parse edir, məcburi sahələri doğrulayır."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._raw_dict = json.load(f)
        except FileNotFoundError:
            raise ConfigValidationError(
                f"Konfiqurasiya faylı tapılmadı: {self.config_path}. "
                f"Sistem bu fayl olmadan İŞƏ DÜŞMƏMƏLİDİR."
            )
        except json.JSONDecodeError as e:
            raise ConfigValidationError(
                f"Konfiqurasiya faylı KORLANIB (JSON sintaksis xətası): {e}. "
                f"Fayl əl ilə redaktə edilibsə, JSON validator-la yoxlayın."
            )

        self._validate_required_keys()
        self._build_namespaces()

        print(f"[OK] Konfiqurasiya yükləndi: {self.config_path} "
              f"(hardware_revision: {self._raw_dict.get('_meta', {}).get('hardware_revision', 'N/A')})")

    def _validate_required_keys(self):
        """Məcburi üst-səviyyə sahələrin mövcudluğunu yoxlayır."""
        missing = [k for k in self.REQUIRED_TOP_LEVEL_KEYS if k not in self._raw_dict]
        if missing:
            raise ConfigValidationError(
                f"Konfiqurasiyada MƏCBURİ sahələr əskikdir: {missing}. "
                f"Sistem bunlar olmadan təhlükəsiz işləyə bilməz — dayandırılır."
            )

    def _build_namespaces(self):
        """
        Dict-ləri SimpleNamespace-ə çevirir ki, `config.rf_frontend.dwell_time_us`
        kimi rahat sintaksislə giriş mümkün olsun (dict["a"]["b"] əvəzinə).
        """
        self.raw = self._raw_dict  # xam dict-ə tam giriş, lazım olsa

        self.rf_frontend = self._dict_to_namespace(self._raw_dict["rf_frontend"])
        self.antenna = self._dict_to_namespace(self._raw_dict["antenna"])
        self.dsp_processing = self._dict_to_namespace(self._raw_dict["dsp_processing"])
        self.flight_platform = self._dict_to_namespace(self._raw_dict["flight_platform"])
        self.return_to_mark = self._dict_to_namespace(self._raw_dict["return_to_mark"])
        self.uwb_boundary = self._dict_to_namespace(self._raw_dict["uwb_boundary"])
        self.network = self._dict_to_namespace(self._raw_dict.get("network", {}))

    @staticmethod
    def _dict_to_namespace(d):
        """Rekursiv olaraq dict-i SimpleNamespace-ə çevirir (nested dict-lər daxil)."""
        if isinstance(d, dict):
            return SimpleNamespace(**{
                k: SystemConfig._dict_to_namespace(v)
                for k, v in d.items()
                if not k.startswith("_comment")  # şərh sahələrini keçək
            })
        elif isinstance(d, list):
            return [SystemConfig._dict_to_namespace(item) for item in d]
        else:
            return d

    def reload(self):
        """
        Faylı YENİDƏN oxuyur — sahə uçuşu zamanı əl ilə konfiqurasiya
        dəyişikliyi edilibsə (məsələn, soil_permittivity sahə ölçməsindən
        sonra yenilənibsə), sistemi YENIDƏN BAŞLATMADAN tətbiq etmək üçün.
        """
        print("[OK] Konfiqurasiya yenidən yüklənir...")
        self.load()

    def get_excluded_bands(self):
        """
        rf_frontend.excluded_bands siyahısını, gpr_frequency_exclusion.py-dəki
        FrequencyExclusionZone formatına HAZIR şəkildə qaytarır.
        """
        bands = getattr(self.rf_frontend, "excluded_bands", [])
        return [
            {
                "start_hz": b.start_hz,
                "stop_hz": b.stop_hz,
                "guard_band_hz": b.guard_band_hz,
                "reason": b.reason,
            }
            for b in bands
        ]


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("TEST 1: Düzgün konfiqurasiya faylı ilə yükləmə")
    print("=" * 55)

    config = SystemConfig(config_path="system_config.json")

    print(f"\nNümunə tipləndirilmiş giriş:")
    print(f"  RF start: {config.rf_frontend.frequency_range.rf_start_hz/1e9:.1f} GHz")
    print(f"  PLL addımı: {config.rf_frontend.sweep_strategy.pll_step_hz/1e6:.0f} MHz")
    print(f"  Torpaq dielektrik sabiti: {config.dsp_processing.soil_permittivity.value}")
    print(f"  Dron kütləsi: {config.return_to_mark.drone_mass_kg} kg")
    print(f"  UWB xətt aralığı: {config.uwb_boundary.line_spacing_m} m")

    excluded = config.get_excluded_bands()
    print(f"\n  İstisna zonaları: {len(excluded)} ədəd")
    for zone in excluded:
        print(f"    {zone['start_hz']/1e6:.0f}-{zone['stop_hz']/1e6:.0f}MHz ({zone['reason']})")

    print("\n" + "=" * 55)
    print("TEST 2: Əskik məcburi sahə ilə fayl (validasiya işləməlidir)")
    print("=" * 55)

    import tempfile, os
    broken_config = {"rf_frontend": {}}  # qəsdən əskik — digər məcburi sahələr yoxdur

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(broken_config, f)
        broken_path = f.name

    try:
        SystemConfig(config_path=broken_path)
        print("[XƏTA] Validasiya İŞLƏMƏDİ — bu, baş verməməli idi!")
    except ConfigValidationError as e:
        print(f"[OK] Validasiya düzgün işlədi, xəta tutuldu:\n     {e}")
    finally:
        os.unlink(broken_path)

    print("\n" + "=" * 55)
    print("TEST 3: Mövcud olmayan fayl (FileNotFoundError halı)")
    print("=" * 55)
    try:
        SystemConfig(config_path="movcud_olmayan_fayl.json")
        print("[XƏTA] Bu, xəta atmalı idi!")
    except ConfigValidationError as e:
        print(f"[OK] Düzgün işlədi:\n     {e}")
