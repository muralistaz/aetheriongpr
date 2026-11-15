"""
============================================================
DIY GPR — Sistem İnfrastrukturu 2: Fault-Tolerance/Reconnect Məntiqi
============================================================
"""

import time
import signal
import logging
from enum import Enum
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class ConnectionState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"      
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"          


class ConnectionWatchdog:
    def __init__(self, name, max_consecutive_failures=3,
                 initial_retry_delay_s=1.0, max_retry_delay_s=30.0,
                 on_failed_callback=None):
        self.name = name
        self.max_consecutive_failures = max_consecutive_failures
        self.initial_retry_delay = initial_retry_delay_s
        self.max_retry_delay = max_retry_delay_s
        self.on_failed_callback = on_failed_callback

        self.state = ConnectionState.HEALTHY
        self.consecutive_failures = 0
        self.total_reconnect_attempts = 0
        self.last_healthy_timestamp = time.time()

        self.logger = logging.getLogger(name)

    def health_check(self):
        raise NotImplementedError("Alt-sinif bu metodu təyin etməlidir.")

    def reconnect(self):
        raise NotImplementedError("Alt-sinif bu metodu təyin etməlidir.")

    def run_check_cycle(self):
        try:
            is_healthy = self.health_check()
        except Exception as e:
            self.logger.warning(f"health_check() özü xəta atdı: {e}")
            is_healthy = False

        if is_healthy:
            if self.state != ConnectionState.HEALTHY:
                self.logger.info(f"Bağlantı BƏRPA OLUNDU (əvvəlki vəziyyət: {self.state.value})")
            self.state = ConnectionState.HEALTHY
            self.consecutive_failures = 0
            self.last_healthy_timestamp = time.time()
            return True

        self.consecutive_failures += 1
        self.logger.warning(f"Sağlamlıq yoxlaması UĞURSUZ (ardıcıl xəta sayı: {self.consecutive_failures})")

        if self.consecutive_failures >= self.max_consecutive_failures:
            self.state = ConnectionState.FAILED
            self.logger.error(f"MAKSIMUM ardıcıl xəta sayına ({self.max_consecutive_failures}) çatıldı — FAILED vəziyyətinə keçilir!")
            if self.on_failed_callback:
                self.on_failed_callback(self)
            return False

        self.state = ConnectionState.RECONNECTING
        retry_delay = min(
            self.initial_retry_delay * (2 ** (self.consecutive_failures - 1)),
            self.max_retry_delay,
        )
        self.logger.info(f"Reconnect cəhdi #{self.total_reconnect_attempts + 1} ({retry_delay:.1f}s gözlədikdən sonra)...")

        time.sleep(retry_delay)
        self.total_reconnect_attempts += 1

        try:
            success = self.reconnect()
        except Exception as e:
            self.logger.warning(f"reconnect() özü xəta atdı: {e}")
            success = False

        if success:
            self.logger.info("Reconnect UĞURLU oldu.")
        else:
            self.logger.warning("Reconnect UĞURSUZ oldu.")

        return success

    def time_since_last_healthy(self):
        return time.time() - self.last_healthy_timestamp


class LimeSDRWatchdog(ConnectionWatchdog):
    def __init__(self, lime_controller, **kwargs):
        super().__init__(name="LimeSDR", **kwargs)
        self.lime_controller = lime_controller

    def health_check(self):
        try:
            import SoapySDR
            devices = SoapySDR.Device.enumerate()
            device_present = len(devices) > 0
            stream_active = (self.lime_controller.rx_stream is not None and device_present)
            return device_present and stream_active
        except Exception as e:
            self.logger.debug(f"health_check xətası: {e}")
            return False

    def reconnect(self):
        try:
            self.lime_controller.close()
        except Exception:
            pass
        try:
            self.lime_controller.connect()
            self.lime_controller.setup_streams()
            return True
        except Exception as e:
            self.logger.warning(f"LimeSDR reconnect uğursuz: {e}")
            return False


class MAVLinkWatchdog(ConnectionWatchdog):
    """
    Cube Orange+ ilə MAVLink bağlantısının sağlamlığını monitor edir.
    ƏLAVƏ: Əgər MAVLink bağlantısı TAM İTİRİLƏRSƏ (FAILED), sadəcə monitorinq
    etmir, MƏCBURİ şəkildə RC/GCS vasitəsilə RTL (Return-to-Launch)
    qərarını işə salır.
    """
    def __init__(self, mavlink_connection_factory, heartbeat_timeout_s=3.0, **kwargs):
        super().__init__(name="MAVLink", **kwargs)
        self.connection_factory = mavlink_connection_factory
        self.heartbeat_timeout = heartbeat_timeout_s
        self.mav = None
        self.last_heartbeat_time = 0

    def health_check(self):
        if self.mav is None:
            return False
        try:
            msg = self.mav.recv_match(type="HEARTBEAT", blocking=False)
            if msg is not None:
                self.last_heartbeat_time = time.time()
            return (time.time() - self.last_heartbeat_time) < self.heartbeat_timeout
        except Exception as e:
            self.logger.debug(f"health_check xətası: {e}")
            return False

    def reconnect(self):
        try:
            if self.mav is not None:
                self.mav.close()
        except Exception:
            pass
        try:
            self.mav = self.connection_factory()
            self.mav.wait_heartbeat(timeout=5)
            self.last_heartbeat_time = time.time()
            return True
        except Exception as e:
            self.logger.warning(f"MAVLink reconnect uğursuz: {e}")
            return False


class SystemSupervisor:
    """
    Bütün watchdog-ları bir yerdə idarə edən mərkəzi dövr.
    ƏLAVƏ 1: Asılıb qalma problemində proses çökməzdən əvvəl arxivə (log-a)
    son sağlamlıq yoxlamasından sonrakı vəziyyəti yazır.
    ƏLAVƏ 2: Fövqəladə hardware/software Killswitch funksiyası.
    """
    def __init__(self, watchdogs, check_interval_s=1.0,
                 enable_systemd_watchdog=True, on_shutdown_callback=None):
        self.watchdogs = watchdogs
        self.check_interval = check_interval_s
        self.enable_systemd_watchdog = enable_systemd_watchdog
        self.on_shutdown_callback = on_shutdown_callback
        self.logger = logging.getLogger("Supervisor")

        self._shutdown_requested = False
        self._notify_socket = None

        if self.enable_systemd_watchdog:
            self._init_systemd_notify()

        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        # Killswitch üçün xüsusi siqnal (məsələn SIGUSR1)
        signal.signal(signal.SIGUSR1, self._handle_killswitch)

    def _init_systemd_notify(self):
        import os
        import socket as socket_module
        notify_socket_path = os.environ.get("NOTIFY_SOCKET")
        if not notify_socket_path:
            self.enable_systemd_watchdog = False
            return
        try:
            self._notify_socket = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_DGRAM)
            self._notify_socket.connect(notify_socket_path)
        except Exception:
            self.enable_systemd_watchdog = False

    def _send_watchdog_ping(self):
        if self._notify_socket:
            try:
                self._notify_socket.send(b"WATCHDOG=1")
            except Exception:
                pass

    def _notify_ready(self):
        if self._notify_socket:
            try:
                self._notify_socket.send(b"READY=1")
            except Exception:
                pass

    def _handle_shutdown_signal(self, signum, frame):
        self.logger.info("SIGTERM/SIGINT alındı — GRACEFUL SHUTDOWN başladılır...")
        self._shutdown_requested = True

    def _handle_killswitch(self, signum, frame):
        """Hardware və ya proqram təminatı səviyyəsində Fövqəladə Killswitch."""
        self.logger.critical("!!! KILLSWITCH AKTİVLƏŞDİRİLDİ !!! Sistem dərhal dayandırılır.")
        self._archive_last_known_state("KILLSWITCH TRIGGERED")
        if self.on_shutdown_callback:
            try:
                self.on_shutdown_callback()
            except Exception:
                pass
        os._exit(1) # Dərhal və sərt çıxış

    def _archive_last_known_state(self, reason):
        """Proses çökməzdən və ya asılıb qalmazdan əvvəl son vəziyyəti arxivləşdirir."""
        try:
            with open("/mnt/user-data/outputs/supervisor_crash_archive.log", "a") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] CRASH/RESTART SEBEBI: {reason}\n")
                for w in self.watchdogs:
                    f.write(f" - {w.name}: Dövr={w.state.value}, Son Sağlamlıq={w.time_since_last_healthy():.1f}s əvvəl\n")
            self.logger.info("Son sağlamlıq vəziyyəti arxivləşdirildi.")
        except Exception as e:
            self.logger.error(f"Arxivləşdirmə xətası: {e}")

    def run_forever(self, stop_condition=None):
        self.logger.info("Supervisor başladı.")
        self._notify_ready()

        while True:
            if self._shutdown_requested:
                break
            if stop_condition and stop_condition():
                break

            all_healthy = True
            for watchdog in self.watchdogs:
                is_ok = watchdog.run_check_cycle()
                if not is_ok:
                    all_healthy = False

            if not all_healthy and self._shutdown_requested == False:
                # Eger sistem asilib qalirsa ve ya xetalar artirsa, son veziyyeti vaxtaşırı yadda saxla
                 self._archive_last_known_state("DEGRADED_OR_HANGING")
                 
            self._send_watchdog_ping()
            time.sleep(self.check_interval)

        self.logger.info("Təmizlik prosedurları icra olunur...")
        if self.on_shutdown_callback:
            try:
                self.on_shutdown_callback()
            except Exception as e:
                self.logger.error(f"on_shutdown_callback xəta atdı: {e}")

        if self._notify_socket:
            try:
                self._notify_socket.send(b"STOPPING=1")
                self._notify_socket.close()
            except Exception:
                pass
        self.logger.info("Supervisor təmiz şəkildə dayandırıldı.")

    print(f"\n[YOXLAMA] Shutdown callback çağırıldımı: "
          f"{'BƏLİ' if shutdown_marker['cleaned_up'] else 'XEYR — XƏTA!'}")
    assert shutdown_marker["cleaned_up"], "XƏTA: on_shutdown_callback çağırılmalı idi!"
    print("[OK] Doğrulandı — supervisor systemd xaricində sakit işlədi VƏ dayananda cleanup icra etdi.")
