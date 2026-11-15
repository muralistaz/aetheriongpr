"""
============================================================
DIY GPR — Sistem İnfrastrukturu 4: Supervisor Giriş Nöqtəsi
============================================================
"""

import sys
import logging
from config_loader import SystemConfig, ConfigValidationError
from fault_tolerance import LimeSDRWatchdog, MAVLinkWatchdog, SystemSupervisor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("SupervisorMain")

def create_watchdogs(config: SystemConfig, lime_controller, mavlink_factory):
    def on_limesdr_failed(watchdog):
        logger.critical("LimeSDR TAM İTİRİLDİ (bütün reconnect cəhdləri uğursuz oldu).")

    def on_mavlink_failed(watchdog):
        logger.critical(
            "MAVLİNK bağlantısı TAM İTİRİLDİ. "
            "MƏCBURİ RTL (Return-to-Launch) siqnalı işə salınır!"
        )
        if watchdog.mav:
            try:
                # RC/GCS RTL əmri göndərmək üçün (MAV_CMD_NAV_RETURN_TO_LAUNCH = 20)
                watchdog.mav.mav.command_long_send(
                    watchdog.mav.target_system, watchdog.mav.target_component,
                    20, 0, 0, 0, 0, 0, 0, 0, 0
                )
                logger.info("MAVLink RTL əmri uğurla göndərildi.")
            except Exception as e:
                logger.error(f"RTL əmri göndərilə bilmədi: {e}")

    watchdogs = []
    if lime_controller is not None:
        watchdogs.append(LimeSDRWatchdog(
            lime_controller=lime_controller, max_consecutive_failures=5,
            initial_retry_delay_s=1.0, max_retry_delay_s=15.0, on_failed_callback=on_limesdr_failed))

    if mavlink_factory is not None:
        watchdogs.append(MAVLinkWatchdog(
            mavlink_connection_factory=mavlink_factory, heartbeat_timeout_s=3.0,
            max_consecutive_failures=5, initial_retry_delay_s=0.5, max_retry_delay_s=10.0,
            on_failed_callback=on_mavlink_failed))

    return watchdogs

def cleanup_resources(lime_controller):
    logger.info("Resurslar təmizlənir...")
    if lime_controller is not None:
        try:
            lime_controller.close()
        except Exception:
            pass

def main():
    logger.info("=== DIY GPR Supervisor başladılır ===")
    try:
        config = SystemConfig(config_path="/home/jetson/gpr_system/system_config.json")
    except ConfigValidationError as e:
        logger.critical(f"Konfiqurasiya yüklənmədi: {e}")
        sys.exit(1)

    lime_controller = None
    mavlink_factory = None

    watchdogs = create_watchdogs(config, lime_controller, mavlink_factory)
    
    supervisor = SystemSupervisor(
        watchdogs=watchdogs, check_interval_s=1.0, enable_systemd_watchdog=True,
        on_shutdown_callback=lambda: cleanup_resources(lime_controller)
    )
    supervisor.run_forever()

if __name__ == "__main__":
    main()
