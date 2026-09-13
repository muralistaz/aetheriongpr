"""
============================================================
DIY GPR — Sistem İnfrastrukturu 4: Supervisor Giriş Nöqtəsi
============================================================

DÜZƏLİŞ SƏBƏBİ: `systemd/gpr-supervisor.service` faylı bu skripti
işə salmağa çalışırdı (`ExecStart=... supervisor_main.py`), amma bu
fayl HEÇ VAXT YAZILMAMIŞDI — yalnız onun istifadə edəcəyi siniflər
(SystemConfig, ConnectionWatchdog və s.) mövcud idi. Bu, systemd
xidmətinin dərhal `FileNotFoundError` ilə çökəcəyi mənasına gəlirdi.

Bu skript, Modul 7-nin bütün komponentlərini (konfiqurasiya,
watchdog-lar, graceful shutdown) BİR YERƏ yığan real giriş nöqtəsidir.

QEYD: LimeSDRController və MAVLink bağlantı obyektləri, Modul 1 və
Modul 4-dən import edilməlidir — bu skriptdə YALNIZ nümunə/placeholder
kimi göstərilib, çünki bu fayl konseptual olaraq YALNIZ Modul 7-yə
(infrastruktur) aiddir, digər modulların öz məntiqini təkrarlamır.
============================================================
"""

import sys
import logging

from config_loader import SystemConfig, ConfigValidationError
from fault_tolerance import (
    LimeSDRWatchdog,
    MAVLinkWatchdog,
    SystemSupervisor,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("SupervisorMain")


def create_watchdogs(config: SystemConfig, lime_controller, mavlink_factory):
    """
    Konfiqurasiyaya əsasən bütün watchdog-ları yaradır.

    QEYD: `on_failed_callback` — hər bağlantı FAILED olanda çağırılan
    funksiyadır. Hazırkı implementasiya YALNIZ loglayır və xəbərdarlıq
    edir — bu, əvvəlki hesabatda (Modul 7, "Bilinən Məhdudiyyətlər")
    açıq qeyd olunmuş, HƏLƏ TAM YAZILMAMIŞ inteqrasiya nöqtəsidir
    (real RTL/failsafe MAVLink əmri, Modul 4-ün return_to_mark
    kodu ilə birləşdirilməlidir).
    """

    def on_limesdr_failed(watchdog):
        logger.critical(
            "LimeSDR TAM İTİRİLDİ (bütün reconnect cəhdləri uğursuz oldu). "
            "GPR data toplama DAYANDI — uçuş missiyası davam edə bilər, "
            "amma radar aşkarlaması İŞLƏMİR. Operatora xəbər verilməlidir."
        )
        # TODO (Modul 4 ilə inteqrasiya): burada MAVLink STATUSTEXT
        # mesajı ilə yer stansiyasına real-vaxt xəbərdarlıq göndərilməlidir

    def on_mavlink_failed(watchdog):
        logger.critical(
            "MAVLİNK (Cube Orange+) bağlantısı TAM İTİRİLDİ. "
            "DİQQƏT: bu, companion-computer səviyyəsində monitorinqdir — "
            "dronun öz failsafe-i (ArduPilot FS_GCS/FS_THR) bu zaman "
            "MÜSTƏQİL olaraq öz qərarını verəcək."
        )

    watchdogs = []

    if lime_controller is not None:
        watchdogs.append(
            LimeSDRWatchdog(
                lime_controller=lime_controller,
                max_consecutive_failures=5,
                initial_retry_delay_s=1.0,
                max_retry_delay_s=15.0,
                on_failed_callback=on_limesdr_failed,
            )
        )

    if mavlink_factory is not None:
        watchdogs.append(
            MAVLinkWatchdog(
                mavlink_connection_factory=mavlink_factory,
                heartbeat_timeout_s=3.0,
                max_consecutive_failures=5,
                initial_retry_delay_s=0.5,
                max_retry_delay_s=10.0,
                on_failed_callback=on_mavlink_failed,
            )
        )

    return watchdogs


def cleanup_resources(lime_controller):
    """
    Graceful shutdown zamanı çağırılır — bütün hardware bağlantılarını
    səliqəylə bağlayır.
    """
    logger.info("Resurslar təmizlənir...")
    if lime_controller is not None:
        try:
            lime_controller.close()
            logger.info("LimeSDR bağlantısı səliqəylə bağlandı.")
        except Exception as e:
            logger.warning(f"LimeSDR bağlanarkən xəta (əhəmiyyətsiz, onsuz da çıxılır): {e}")


def main():
    logger.info("=== DIY GPR Supervisor başladılır ===")

    # --- 1. Konfiqurasiyanı yüklə (uğursuz olsa, DƏRHAL dayan) ---
    try:
        config = SystemConfig(config_path="/home/jetson/gpr_system/system_config.json")
    except ConfigValidationError as e:
        logger.critical(f"Konfiqurasiya yüklənmədi, sistem BAŞLAYA BİLMİR: {e}")
        sys.exit(1)

    # --- 2. Hardware bağlantı obyektlərini hazırla ---
    # QEYD: Real sistemdə, bunlar Modul 1 (limesdr_controller.py) və
    # Modul 4-dən (MAVLink) import edilməlidir. Buradakı importlar
    # şərti (try/except) saxlanılıb ki, bu fayl bu kitabxanalar
    # quraşdırılmadan da test edilə bilsin.
    lime_controller = None
    try:
        from limesdr_controller import LimeSDRController
        lime_controller = LimeSDRController(sample_rate_hz=config.rf_frontend.__dict__.get("sample_rate_hz", 10e6))
        lime_controller.connect()
        lime_controller.setup_streams()
    except ImportError:
        logger.warning("limesdr_controller modulu tapılmadı — LimeSDR watchdog-u KEÇİLİR (yalnız test mühiti üçün qəbul edilə bilər).")
    except Exception as e:
        logger.warning(f"LimeSDR ilkin qoşulma uğursuz oldu: {e} — watchdog buna baxmayaraq yaradılacaq, reconnect cəhd edəcək.")

    mavlink_factory = None
    try:
        from pymavlink import mavutil
        mavlink_factory = lambda: mavutil.mavlink_connection("/dev/ttyACM0", baud=57600)
    except ImportError:
        logger.warning("pymavlink tapılmadı — MAVLink watchdog-u KEÇİLİR (yalnız test mühiti üçün qəbul edilə bilər).")

    # --- 3. Watchdog-ları qur ---
    watchdogs = create_watchdogs(config, lime_controller, mavlink_factory)

    if not watchdogs:
        logger.warning(
            "HEÇ BİR watchdog yaradılmadı (nə LimeSDR, nə MAVLink mövcuddur). "
            "Supervisor işə düşəcək, amma HEÇ NƏYİ monitor etməyəcək — "
            "bu, real uçuşda QƏBUL EDİLƏ BİLMƏZ, yalnız test mühitidir."
        )

    # --- 4. Supervisor-u işə sal ---
    supervisor = SystemSupervisor(
        watchdogs=watchdogs,
        check_interval_s=1.0,
        enable_systemd_watchdog=True,
        on_shutdown_callback=lambda: cleanup_resources(lime_controller),
    )

    supervisor.run_forever()  # SIGTERM/SIGINT alana qədər əbədi işləyir

    logger.info("=== Supervisor dayandı ===")


if __name__ == "__main__":
    main()
