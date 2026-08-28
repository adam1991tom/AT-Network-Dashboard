"""AT Network Dashboard v2 application package."""

# Apply small compatibility patches before the monitoring modules import the
# UniFi client.  This keeps the collector keyed to the real speed-test run time
# rather than UniFi's changing status timestamp.
from app import unifi_speedtest_fix as _unifi_speedtest_fix  # noqa: F401,E402
