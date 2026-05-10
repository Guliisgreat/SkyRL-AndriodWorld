# AndroidWorld 2026+Swipe+Tier4 — ADB-exclusive tasks with pixel swipe support.
#
# Layers on top of androidworld:2026plusswipe (which has swipe patches + optimizations).
# Adds 50 tier4 ADB-exclusive task modules and configures the server to serve
# only tier4 tasks.
#
# Build (from docker/ directory):
#   docker build -f androidworld_2026plusswipe_tier4/Dockerfile \
#     -t androidworld:2026plusswipe_tier4 .
#
# Requires: androidworld:2026plusswipe

FROM androidworld:2026plusswipe

WORKDIR /data

# Copy tier4 task modules into skyrl_server package
COPY android/skyrl_server/tier4/ /data/skyrl_server/tier4/

# Update registry_ext.py with tier4 task registration (50 tasks)
COPY android/skyrl_server/registry_ext.py /data/skyrl_server/registry_ext.py

# Merged env.py: 2026plusswipe optimizations + TASK_FAMILY env var support
COPY androidworld_2026plusswipe_tier4/env.py /data/skyrl_server/env.py

# Shrink AVD guest RAM from 16 GB → 4 GB to lower per-container host footprint.
# Resident usage drops roughly 10 GB → ~4 GB. Tradeoff: heavy multi-app tasks may
# OOM under memory pressure. Smoke-test before committing to this in production.
RUN sed -i 's/^hw\.ramSize = .*/hw.ramSize = 4096/' /root/.android/avd/AWAvd.avd/config.ini

# Default to tier4 task family with sequential sampling.
# TASK_FAMILY  -> read by env.py (line 115) as runtime override
# ENV_TASK_FAMILY -> read by server.py (line 90) as constructor arg
ENV TASK_FAMILY=tier4
ENV ENV_TASK_FAMILY=tier4
ENV ENV_SAMPLE_MODE=sequential

ENTRYPOINT ["bash", "/data/entrypoint.sh"]
