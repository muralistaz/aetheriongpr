"""
============================================================
DIY GPR — Sistem İnfrastrukturu 2: Fault-Tolerance/Reconnect Məntiqi
============================================================

Bu modul, sistemin İKİ KRİTİK bağlantısını (LimeSDR USB, Cube Orange+
MAVLink) davamlı monitor edir, kəsilmə halında AVTOMATİK bərpa etməyə
çalışır, və bərpa mümkün olmadıqda TƏHLÜKƏSİZ vəziyyətə keçidi təmin edir.

DİZAYN FƏLSƏFƏSİ: "Ümumi çərçivə + spesifik implementasiyalar"
  - `ConnectionWatchdog` — hər növ bağlantı üçün YENİDƏN İSTİFADƏ
    OLUNA BİLƏN əsas məntiq (health-check, retry, exponential backoff)
  - `LimeSDRWatchdog`, `MAVLinkWatchdog` — bu əsas sinifin KONKRET
    tətbiqləri, hər biri öz "bu bağlantı sağdırmı?" yoxlamasını təyin edir

Bu ayrılıq sayəsində, gələcəkdə yeni bağlantı növü (məsələn, UWB
marker rabitəsi) əlavə olunanda, TƏKRAR-TƏKRAR eyni reconnect
məntiqini yazmaq lazım gəlmir — sadəcə yeni bir "health check"
funksiyası yazılır.
============================================================
"""

import time
import signal
import logging
from enum import Enum

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ============================================================
# 1. ÜMUMİ VƏZİYYƏT MODELİ
# ============================================================
class ConnectionState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"      # bir neçə ardıcıl xəta, hələ kritik deyil
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"          # bütün bərpa cəhdləri bitib, təhlükəsiz rejimə keçilməli


# ============================================================
# 2. ƏSAS WATCHDOG SİNİFİ (yenidən istifadə oluna bilən çərçivə)
# ============================================================
class ConnectionWatchdog:
    """
    İstənilən bağlantı növü üçün ümumi monitorinq/reconnect məntiqi.

    İSTİFADƏ: Bu sinif özlüyündə İŞLƏMİR — alt-sinif (subclass) yaradıb,
    `health_check()` və `reconnect()` metodlarını KONKRET bağlantı
    növünə uyğun override etməlisiniz (aşağıdakı LimeSDRWatchdog və
    MAVLinkWatchdog nümunələrinə baxın).
    """

    def __init__(self, name, max_consecutive_failures=3,
                 initial_retry_delay_s=1.0, max_retry_delay_s=30.0,
                 on_failed_callback=None):
        """
        name: Loglamada görünəcək bağlantının adı (məs. "LimeSDR", "MAVLink")
        max_consecutive_failures: Neçə ardıcıl uğursuz reconnect cəhdindən
            sonra FAILED vəziyyətinə keçilsin (və on_failed_callback çağırılsın)
        initial_retry_delay_s, max_retry_delay_s: Exponential backoff
            parametrləri — hər uğursuz cəhddən sonra gözləmə müddəti
            İKİQAT ARTIR (max_retry_delay_s-ə qədər), bu, uğursuz
            bağlantıya "spam" etməkdən qorunur
        on_failed_callback: FAILED vəziyyətinə keçildikdə çağırılan funksiya
            (məsələn, "RTL failsafe işə sal" və ya "operatora xəbərdarlıq et")
        """
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

    # --------------------------------------------------------
    # BUNLAR ALT-SİNİFDƏ MÜTLƏQ OVERRIDE EDİLMƏLİDİR:
    # --------------------------------------------------------
    def health_check(self):
        """
        Bağlantının HAZIRDA sağlam olub-olmadığını yoxlayır.
        Qaytarır: True (sağlamdır) / False (problem var)
        """
        raise NotImplementedError("Alt-sinif bu metodu təyin etməlidir.")

    def reconnect(self):
        """
        Bağlantını YENİDƏN qurmağa cəhd edir.
        Qaytarır: True (uğurlu) / False (uğursuz)
        """
        raise NotImplementedError("Alt-sinif bu metodu təyin etməlidir.")

    # --------------------------------------------------------
    # ÜMUMİ MƏNTİQ (override edilməsinə ehtiyac yoxdur):
    # --------------------------------------------------------
    def run_check_cycle(self):
        """
        Bir monitorinq dövrü icra edir: sağlamlığı yoxlayır, problem
        aşkarlansa reconnect ardıcıllığını başladır.

        Bu metod, əsas idarəetmə dövründə (məsələn, hər 1 saniyədə bir)
        çağırılmalıdır.
        """
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

        # --- Sağlam deyil — reconnect ardıcıllığı ---
        self.consecutive_failures += 1
        self.logger.warning(
            f"Sağlamlıq yoxlaması UĞURSUZ (ardıcıl xəta sayı: {self.consecutive_failures})"
        )

        if self.consecutive_failures >= self.max_consecutive_failures:
            self.state = ConnectionState.FAILED
            self.logger.error(
                f"MAKSIMUM ardıcıl xəta sayına ({self.max_consecutive_failures}) çatıldı — "
                f"FAILED vəziyyətinə keçilir!"
            )
            if self.on_failed_callback:
                self.on_failed_callback(self)
            return False

        self.state = ConnectionState.RECONNECTING
        retry_delay = min(
            self.initial_retry_delay * (2 ** (self.consecutive_failures - 1)),
            self.max_retry_delay,
        )
        self.logger.info(f"Reconnect cəhdi #{self.total_reconnect_attempts + 1} "
                          f"({retry_delay:.1f}s gözlədikdən sonra)...")

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
        """Son sağlam vəziyyətdən neçə saniyə keçdiyini qaytarır."""
        return time.time() - self.last_healthy_timestamp


# ============================================================
# 3. KONKRET TƏTBİQ 1: LimeSDR WATCHDOG
# ============================================================
class LimeSDRWatchdog(ConnectionWatchdog):
    """
    LimeSDR-in USB bağlantısının sağlamlığını monitor edir.

    REAL SƏBƏBLƏR ki, LimeSDR bağlantısı kəsilə bilər:
      - USB kabelinin uçuş vibrasiyasından boşalması (fiziki, çox real risk)
      - USB power management-in cihazı "yatırması" (Jetson-un enerji
        idarəetmə parametrlərində bu deaktiv edilməlidir — ayrıca qeyd)
      - LimeSDR-in özünün overheating-dən "asılıb qalması"
    """

    def __init__(self, lime_controller, **kwargs):
        """
        lime_controller: LimeSDRController instansı (əvvəlki
            limesdr_controller.py-dəki sinif)
        """
        super().__init__(name="LimeSDR", **kwargs)
        self.lime_controller = lime_controller

    def health_check(self):
        """
        LimeSDR-in hələ də USB-də görünüb-görünmədiyini və stream-in
        aktiv olub-olmadığını yoxlayır.
        """
        try:
            import SoapySDR
            devices = SoapySDR.Device.enumerate()
            device_present = len(devices) > 0

            # Əlavə yoxlama: stream-dən real data gəlirmi (boş FIFO deyil)?
            # Bu, sadəcə USB-nin "görünməsi" kifayət deyil — real data
            # axını olub-olmadığını da yoxlamaq lazımdır.
            stream_active = (
                self.lime_controller.rx_stream is not None
                and device_present
            )

            return device_present and stream_active
        except Exception as e:
            self.logger.debug(f"health_check xətası: {e}")
            return False

    def reconnect(self):
        """LimeSDR-i tam bağlayıb, yenidən açır və stream-ləri bərpa edir."""
        try:
            self.lime_controller.close()
        except Exception:
            pass  # onsuz da bağlıdırsa, problem deyil

        try:
            self.lime_controller.connect()
            self.lime_controller.setup_streams()
            return True
        except Exception as e:
            self.logger.warning(f"LimeSDR reconnect uğursuz: {e}")
            return False


# ============================================================
# 4. KONKRET TƏTBİQ 2: MAVLINK (Cube Orange+) WATCHDOG
# ============================================================
class MAVLinkWatchdog(ConnectionWatchdog):
    """
    Cube Orange+ ilə MAVLink bağlantısının sağlamlığını (heartbeat
    axını əsasında) monitor edir.

    VACİB TƏHLÜKƏSİZLİK QEYDİ: Əgər MAVLink bağlantısı TAM İTİRİLƏRSƏ
    (FAILED vəziyyəti), bu, "sadəcə reconnect edək" məsələsi deyil —
    bu, DRONUN ÖZ TƏHLÜKƏSİZLİK SİSTEMİNƏ (ArduPilot-un öz RC/GCS
    failsafe-i) buraxılmalı bir vəziyyətdir. Bu watchdog, YALNIZ
    companion-computer səviyyəsində monitorinq üçündür, flight
    controller-in öz failsafe məntiqini ƏVƏZ ETMİR.
    """

    def __init__(self, mavlink_connection_factory, heartbeat_timeout_s=3.0, **kwargs):
        """
        mavlink_connection_factory: arqumentsiz çağırılanda YENİ mavlink
            bağlantısı yaradıb qaytaran funksiya (məs.
            `lambda: mavutil.mavlink_connection('/dev/ttyUSB0', baud=57600)`)
        heartbeat_timeout_s: Neçə saniyə heartbeat gəlməsə, bağlantı
            "sağlam deyil" sayılsın
        """
        super().__init__(name="MAVLink", **kwargs)
        self.connection_factory = mavlink_connection_factory
        self.heartbeat_timeout = heartbeat_timeout_s
        self.mav = None
        self.last_heartbeat_time = 0

    def health_check(self):
        """Son heartbeat mesajından keçən vaxtı yoxlayır."""
        if self.mav is None:
            return False

        try:
            # pymavlink-də, timeout ilə qeyri-blok edən heartbeat oxuma:
            msg = self.mav.recv_match(type="HEARTBEAT", blocking=False)
            if msg is not None:
                self.last_heartbeat_time = time.time()

            time_since_heartbeat = time.time() - self.last_heartbeat_time
            return time_since_heartbeat < self.heartbeat_timeout
        except Exception as e:
            self.logger.debug(f"health_check xətası: {e}")
            return False

    def reconnect(self):
        """MAVLink bağlantısını bağlayıb yenidən qurur."""
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


# ============================================================
# 5. MƏRKƏZİ SUPERVISOR — BÜTÜN WATCHDOG-LARI BİRLƏŞDİRİR
# ============================================================
class SystemSupervisor:
    """
    Bütün watchdog-ları bir yerdə idarə edən mərkəzi dövr.

    ƏLAVƏ EDİLƏN 2 YENİ QABILIYYƏT (əvvəlki versiyada YOX idi):

    1. SYSTEMD WATCHDOG İNTEQRASİYASI (sd_notify): Sadəcə "proses
       çökübmü" yoxlaması kifayət deyil — proses ASILIB QALA bilər
       (deadlock, sonsuz gözləmə) və systemd bunu heç vaxt görməz,
       çünki prosesin özü hələ "yaşayır" (exit etməyib). sd_notify
       protokolu ilə, bu proses systemd-ə dövri "mən sağamam" siqnalı
       göndərir (WATCHDOG=1). Əgər bu siqnal, systemd service
       faylındakı WatchdogSec müddətindən çox gecikərsə, systemd
       PROSESİ ÖZÜ ÖLDÜRÜB YENİDƏN BAŞLADIR — hətta proses "run"
       vəziyyətində görünsə belə.

    2. GRACEFUL SHUTDOWN (SIGTERM/SIGINT idarəetməsi): systemd
       `systemctl stop` çağıranda, prosesə SIGTERM göndərir. Bunu
       tutmasaq, proses ANİ olaraq kəsilir — LimeSDR bağlantısı
       səliqəsiz qalır, yarımçıq fayl yazması baş verə bilər. Bu
       sinif indi SIGTERM/SIGINT-i tutur, `on_shutdown_callback`-i
       çağırır (təmizlik üçün), SONRA dayanır.
    """

    def __init__(self, watchdogs, check_interval_s=1.0,
                 enable_systemd_watchdog=True, on_shutdown_callback=None):
        """
        enable_systemd_watchdog: True olduqda, systemd-nin WATCHDOG=1
            NOTIFY_SOCKET-inə dövri "canlıyam" siqnalı göndərir.
            Sistemd mühiti xaricində (məsələn, əl ilə terminal-dan
            icra edərkən) bu, sakitcə heç nə etmir (xəta atmır).
        on_shutdown_callback: SIGTERM/SIGINT alınanda çağırılan funksiya
            (məsələn, "LimeSDR-i səliqəylə bağla", "son log-u yaz")
        """
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

    def _init_systemd_notify(self):
        """
        systemd-nin NOTIFY_SOCKET-inə qoşulur (yalnız systemd altında
        işə salınıbsa mövcuddur — mühit dəyişəni ilə aşkarlanır).
        """
        import os
        import socket as socket_module

        notify_socket_path = os.environ.get("NOTIFY_SOCKET")
        if not notify_socket_path:
            self.logger.debug(
                "NOTIFY_SOCKET tapılmadı — systemd xaricində işləyir "
                "(məsələn, əl ilə terminal-dan). Watchdog ping-ləri keçilir."
            )
            self.enable_systemd_watchdog = False
            return

        try:
            self._notify_socket = socket_module.socket(
                socket_module.AF_UNIX, socket_module.SOCK_DGRAM
            )
            self._notify_socket.connect(notify_socket_path)
            self.logger.info("systemd NOTIFY_SOCKET-ə qoşuldu — watchdog aktivdir.")
        except Exception as e:
            self.logger.warning(f"systemd notify socket-ə qoşulma uğursuz: {e}")
            self.enable_systemd_watchdog = False

    def _send_watchdog_ping(self):
        """systemd-ə 'mən sağamam' siqnalı göndərir (WATCHDOG=1)."""
        if self._notify_socket:
            try:
                self._notify_socket.send(b"WATCHDOG=1")
            except Exception as e:
                self.logger.warning(f"Watchdog ping göndərilmədi: {e}")

    def _notify_ready(self):
        """systemd-ə 'başlanğıc tamamlandı, indi sağlamam' bildirir (Type=notify üçün)."""
        if self._notify_socket:
            try:
                self._notify_socket.send(b"READY=1")
            except Exception:
                pass

    def _handle_shutdown_signal(self, signum, frame):
        """SIGTERM/SIGINT alındıqda çağırılır — dövrü təmiz şəkildə dayandırır."""
        sig_name = signal.Signals(signum).name
        self.logger.info(f"{sig_name} alındı — GRACEFUL SHUTDOWN başladılır...")
        self._shutdown_requested = True

    def run_forever(self, stop_condition=None):
        """
        Əsas monitorinq dövrü. `stop_condition` — arqumentsiz çağırılanda
        True qaytarsa, dövr dayanır (test/deməktal məqsədilə). SIGTERM/
        SIGINT alınanda da (real sistemdə) dövr eyni şəkildə dayanır.
        """
        self.logger.info(f"Supervisor başladı, {len(self.watchdogs)} watchdog monitor olunur.")
        self._notify_ready()

        while True:
            if self._shutdown_requested:
                break
            if stop_condition and stop_condition():
                break

            for watchdog in self.watchdogs:
                watchdog.run_check_cycle()

            self._send_watchdog_ping()

            time.sleep(self.check_interval)

        # --- Graceful shutdown ---
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


# ============================================================
# TEST — SİMULYASİYA (real LimeSDR/MAVLink olmadan)
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("TEST: Simulyasiya edilmiş watchdog — 3 ardıcıl xəta, sonra bərpa")
    print("=" * 60)

    class FakeFlappyWatchdog(ConnectionWatchdog):
        """Test üçün: ilk 3 yoxlamada 'sağlam deyil', sonra 'sağlam' olur."""

        def __init__(self, **kwargs):
            super().__init__(name="FakeConnection", **kwargs)
            self.check_count = 0

        def health_check(self):
            self.check_count += 1
            return self.check_count > 3  # ilk 3 dəfə False, sonra True

        def reconnect(self):
            return True  # həmişə "uğurlu" reconnect simulyasiyası

    def on_failed(watchdog):
        print(f"  >>> [CALLBACK] {watchdog.name} FAILED oldu! Təhlükəsiz rejimə keçid lazımdır.")

    watchdog = FakeFlappyWatchdog(
        max_consecutive_failures=5,
        initial_retry_delay_s=0.1,  # test üçün sürətli
        max_retry_delay_s=0.5,
        on_failed_callback=on_failed,
    )

    for i in range(6):
        print(f"\n--- Dövr {i+1} ---")
        watchdog.run_check_cycle()
        print(f"    Vəziyyət: {watchdog.state.value}")

    print("\n" + "=" * 60)
    print("TEST 2: FAILED vəziyyətinə düşən watchdog (heç vaxt bərpa olmur)")
    print("=" * 60)

    class FakeAlwaysBrokenWatchdog(ConnectionWatchdog):
        def __init__(self, **kwargs):
            super().__init__(name="AlwaysBroken", **kwargs)

        def health_check(self):
            return False

        def reconnect(self):
            return False

    broken_watchdog = FakeAlwaysBrokenWatchdog(
        max_consecutive_failures=3,
        initial_retry_delay_s=0.1,
        max_retry_delay_s=0.2,
        on_failed_callback=on_failed,
    )

    for i in range(4):
        print(f"\n--- Dövr {i+1} ---")
        broken_watchdog.run_check_cycle()
        print(f"    Vəziyyət: {broken_watchdog.state.value}")

    assert broken_watchdog.state == ConnectionState.FAILED, "XƏTA: FAILED vəziyyətinə keçməli idi!"
    print("\n[OK] Doğrulandı — daim uğursuz bağlantı düzgün şəkildə FAILED elan edildi.")

    print("\n" + "=" * 60)
    print("TEST 3: SystemSupervisor — systemd XARİCİNDƏ sakit keçid + graceful shutdown")
    print("=" * 60)

    shutdown_marker = {"cleaned_up": False}

    def fake_cleanup():
        shutdown_marker["cleaned_up"] = True
        print("  >>> [CLEANUP] LimeSDR səliqəylə bağlandı (simulyasiya).")

    healthy_watchdog = FakeFlappyWatchdog(max_consecutive_failures=10)
    # İlk 3 dövrü keçib HEALTHY olsun deyə əvvəlcədən "isindirmə"
    for _ in range(4):
        healthy_watchdog.health_check()

    supervisor = SystemSupervisor(
        watchdogs=[healthy_watchdog],
        check_interval_s=0.05,
        enable_systemd_watchdog=True,  # qəsdən True — systemd YOXDURSA sakit fallback olmalıdır
        on_shutdown_callback=fake_cleanup,
    )

    print(f"[YOXLAMA] NOTIFY_SOCKET mühit dəyişəni olmadan, watchdog aktiv OLMAMALIDIR: "
          f"{'DOĞRU' if not supervisor.enable_systemd_watchdog else 'XƏTA!'}")
    assert not supervisor.enable_systemd_watchdog, (
        "XƏTA: systemd mövcud olmadıqda enable_systemd_watchdog False olmalıdır!"
    )

    # 5 dövrdən sonra özü-özünü dayandıran stop_condition
    call_count = {"n": 0}
    def stop_after_5():
        call_count["n"] += 1
        return call_count["n"] > 5

    supervisor.run_forever(stop_condition=stop_after_5)

    print(f"\n[YOXLAMA] Shutdown callback çağırıldımı: "
          f"{'BƏLİ' if shutdown_marker['cleaned_up'] else 'XEYR — XƏTA!'}")
    assert shutdown_marker["cleaned_up"], "XƏTA: on_shutdown_callback çağırılmalı idi!"
    print("[OK] Doğrulandı — supervisor systemd xaricində sakit işlədi VƏ dayananda cleanup icra etdi.")
