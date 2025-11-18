"""
Modem Check model for storing cable modem diagnostic data.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class ModemCheck(Base):
    """
    Modem diagnostic check data.

    Stores extracted metrics for quick queries plus full JSON data.
    Compatible with data from Arris XB8, Motorola DM1000, and Xfinity modems.
    """
    __tablename__ = "modem_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    modem_id = Column(String(255), nullable=False, index=True)  # Format: TYPE-MAC
    modem_type = Column(String(100), nullable=True, index=True)
    check_time = Column(DateTime, nullable=False, index=True)
    filename = Column(String(255), nullable=False, unique=True, index=True)

    # System info
    firmware = Column(String(255), nullable=True)
    uptime_seconds = Column(Integer, nullable=True)
    system_time = Column(DateTime, nullable=True)

    # Signal quality metrics (for quick queries)
    avg_downstream_power = Column(Float, nullable=True)
    avg_downstream_snr = Column(Float, nullable=True)
    avg_upstream_power = Column(Float, nullable=True)
    total_corrected_errors = Column(Integer, nullable=True)
    total_uncorrected_errors = Column(Integer, nullable=True)

    # Speed test results
    speedtest_enabled = Column(Integer, nullable=True)  # 0=disabled, 1=enabled
    iperf3_upload = Column(String(50), nullable=True)  # e.g., "45.2 Mbps"
    iperf3_download = Column(String(50), nullable=True)
    speedtest_server_name = Column(String(255), nullable=True)
    speedtest_server_id = Column(String(50), nullable=True)
    speedtest_latency = Column(Float, nullable=True)
    speedtest_max_latency = Column(Float, nullable=True)
    speedtest_jitter = Column(Float, nullable=True)
    speedtest_packet_loss = Column(Float, nullable=True)
    speedtest_dl_latency = Column(Float, nullable=True)
    speedtest_ul_jitter = Column(Float, nullable=True)

    # Ping test results
    ping_google_avg = Column(Float, nullable=True)
    ping_google_loss = Column(Float, nullable=True)
    ping_google_jitter = Column(Float, nullable=True)
    ping_google_max_latency = Column(Float, nullable=True)
    ping_cloudflare_avg = Column(Float, nullable=True)
    ping_cloudflare_loss = Column(Float, nullable=True)
    ping_cloudflare_jitter = Column(Float, nullable=True)
    ping_cloudflare_max_latency = Column(Float, nullable=True)

    # Client information
    client_version = Column(String(50), nullable=True)
    client_os = Column(String(50), nullable=True)
    client_arch = Column(String(50), nullable=True)

    # Network information
    detection_status = Column(String(50), nullable=True)
    public_ip = Column(String(45), nullable=True)  # IPv6 compatible
    asn = Column(String(50), nullable=True)
    isp_name = Column(String(255), nullable=True)
    ip_city = Column(String(255), nullable=True)
    ip_country = Column(String(255), nullable=True)

    # Full JSON data (PostgreSQL JSONB for efficient querying)
    full_data = Column(JSONB, nullable=False)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_modem_check_modem_time', 'modem_id', 'check_time'),
        Index('idx_modem_check_type', 'modem_type'),
    )

    def __repr__(self):
        return f"<ModemCheck(modem_id='{self.modem_id}', check_time='{self.check_time}')>"
