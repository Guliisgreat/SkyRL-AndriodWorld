FROM androidworld:2026

# Patch actuation.py: add pixel-coord swipe + time.sleep(2) after actions
COPY actuation.py /usr/local/lib/python3.11/site-packages/android_world/env/actuation.py

# Patch json_action.py: accept list direction for pixel-coord swipe
COPY json_action.py /usr/local/lib/python3.11/site-packages/android_world/env/json_action.py

# Patch interface.py: skip get_state() for pixel-coord actions
COPY interface.py /usr/local/lib/python3.11/site-packages/android_world/env/interface.py

# Patch env.py: remove time.sleep(3) white-screen loop, use 10*complexity budget
COPY env.py /data/skyrl_server/env.py

ENTRYPOINT ["bash", "/data/entrypoint.sh"]
