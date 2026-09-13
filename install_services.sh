#!/bin/bash
# ============================================================
# DIY GPR — Systemd Xidmətlərinin Quraşdırılması
# ============================================================
# Jetson Orin Nano-da, root/sudo hüquqları ilə İCRA EDİLMƏLİDİR:
#   sudo bash install_services.sh
#
# Bu skript İDEMPOTENT-dir (bir neçə dəfə icra edilsə də, eyni,
# təhlükəsiz nəticəni verir) — artıq quraşdırılmış xidmətin üzərinə
# sadəcə yenidən yazır, xəta vermir.
# ============================================================

set -e  # istənilən əmr uğursuz olsa, dərhal dayan (səssiz-səssiz davam etmə)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== DIY GPR Systemd Xidmətlərinin Quraşdırılması ==="

# --- Root hüququ yoxlaması ---
if [ "$EUID" -ne 0 ]; then
    echo "XƏTA: Bu skript root hüquqları ilə icra edilməlidir (sudo istifadə edin)."
    exit 1
fi

# --- Xidmət fayllarını köçür ---
echo "[1/4] Xidmət faylları köçürülür..."
cp "$SCRIPT_DIR/gpr-main.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/gpr-supervisor.service" "$SYSTEMD_DIR/"

# --- systemd-ə yeni faylları "tanıt" ---
echo "[2/4] systemd konfiqurasiyası yenilənir (daemon-reload)..."
systemctl daemon-reload

# --- Boot zamanı avtomatik başlamaq üçün aktivləşdir ---
echo "[3/4] Xidmətlər aktivləşdirilir (boot-da avtomatik başlamaq üçün)..."
systemctl enable gpr-main.service
systemctl enable gpr-supervisor.service

# --- İndi başlat (növbəti reboot-u gözləmədən) ---
echo "[4/4] Xidmətlər indi başladılır..."
systemctl start gpr-main.service
systemctl start gpr-supervisor.service

echo ""
echo "=== Quraşdırma tamamlandı ==="
echo ""
echo "Statusu yoxlamaq üçün:"
echo "  systemctl status gpr-main.service"
echo "  systemctl status gpr-supervisor.service"
echo ""
echo "Canlı logları izləmək üçün:"
echo "  journalctl -u gpr-main -f"
echo "  journalctl -u gpr-supervisor -f"
echo ""
echo "Dayandırmaq üçün (məsələn, texniki xidmət üçün):"
echo "  sudo systemctl stop gpr-main.service gpr-supervisor.service"
